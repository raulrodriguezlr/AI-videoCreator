"""LTX-Desktop discovery client — health + installed-model listing.

LTX-Desktop (https://github.com/Lightricks/LTX-Desktop) is Lightricks' local
app that generates video with LTX models on an NVIDIA GPU (or via LTX cloud
"API mode" on unsupported hardware). It runs a FastAPI backend whose base URL
defaults to ``http://localhost:8000`` and exposes, among others:

- ``GET  /health``                    — server liveness
- ``GET  /api/generate/models-specs`` — the generation models the app can run,
  split into ``local_models`` (on-device) and ``api_models`` (LTX cloud), each
  ``{pipeline, spec:{display_name, supported_resolutions_durations, ...}}``

This module reads that catalog so the UI can show *which models you actually
have installed* in the provider dropdown — the same role Veo's hard-coded model
list plays, but discovered live. It is intentionally read-only: the generation
path (``POST /api/generate``) is migrated separately.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal

import httpx

from videocreator.domain.ports import StoragePort
from videocreator.domain.value_objects import (
    ClipArtifact,
    ImageRef,
    ProviderHealth,
    ScenePrompt,
)
from videocreator.infrastructure.providers.base import CLIP_BUCKET
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderQuotaError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# A single generation can take minutes on a local GPU — far longer than the
# short discovery timeout used for /health and /models-specs.
_GENERATION_TIMEOUT_S = 1800.0

# LTX-Desktop's bundled FastAPI backend (ltx2_server.py) listens on this fixed
# port by default and guards every route with a per-session bearer token. Both
# the port and token are passed to that process via env, so we read them back
# from the same-user process for zero-config integration (see discover()).
# LTX-Desktop only accepts these specific duration values (seconds).
_LTX_VALID_DURATIONS = (5, 6, 8, 10, 12, 14, 16, 18, 20)

DEFAULT_LTX_DESKTOP_PORT = 41954


def _clamp_duration(raw: int) -> int:
    """Snap a requested duration to the nearest LTX-Desktop-accepted value."""
    return min(_LTX_VALID_DURATIONS, key=lambda d: abs(d - raw))


def discover_ltx_desktop() -> tuple[str, str] | None:
    """Find the running LTX-Desktop backend; return ``(base_url, auth_token)``.

    Reads the bundled ``ltx2_server.py`` process's environment (same user, no
    admin needed) for ``LTX_PORT`` and ``LTX_AUTH_TOKEN``. Returns ``None`` when
    the app isn't running or psutil is unavailable — callers fall back to the
    configured URL.
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        for proc in psutil.process_iter(["cmdline"]):
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "ltx2_server.py" in cmdline:
                try:
                    env = proc.environ()
                except (psutil.AccessDenied, ProcessLookupError):
                    # Process exited or access denied — try next one
                    continue
                port = env.get("LTX_PORT") or str(DEFAULT_LTX_DESKTOP_PORT)
                return f"http://127.0.0.1:{port}", env.get("LTX_AUTH_TOKEN", "")
    except Exception as exc:
        log.debug("ltx_desktop.discover.failed", error=str(exc))
    return None

# LTX-Desktop resolution label → (width, height) for the produced ClipArtifact.
_RESOLUTION_WH: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

# Map LTX-Desktop resolution labels to (width, height) for `max_resolution`.
_RESOLUTION_PIXELS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    "2160p": (3840, 2160),
}


@dataclass(frozen=True, slots=True)
class LtxModel:
    """A generation model the LTX-Desktop app can run."""

    id: str  # the `pipeline` value, e.g. "fast" / "pro" — what /generate expects
    display_name: str
    source: Literal["local", "api"]
    resolutions: tuple[str, ...]
    max_duration_s: int


class LtxDesktopClient:
    """Thin async client over the LTX-Desktop FastAPI backend (read-only)."""

    def __init__(self, base_url: str, *, token: str = "", timeout: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @classmethod
    def autodiscover(cls, *, fallback_url: str, timeout: float = 3.0) -> LtxDesktopClient:
        """Build a client pointed at the running LTX-Desktop (port + bearer token
        read from its process), falling back to ``fallback_url`` if not found."""
        found = discover_ltx_desktop()
        if found is not None:
            base_url, token = found
            return cls(base_url, token=token, timeout=timeout)
        return cls(fallback_url, timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def is_up(self) -> bool:
        """Return True iff the LTX-Desktop backend answers /health with 200."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/health", headers=self._headers)
            return resp.status_code == httpx.codes.OK
        except httpx.HTTPError as exc:
            log.debug("ltx_desktop.health.unreachable", error=str(exc))
            return False

    async def list_models(self) -> list[LtxModel]:
        """Return the installed/available generation models (local + cloud).

        Raises ``httpx.HTTPError`` if the backend is unreachable or errors, so
        callers can distinguish "no models" from "server down".
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/api/generate/models-specs", headers=self._headers
            )
            resp.raise_for_status()
            payload = resp.json()
        models: list[LtxModel] = []
        for item in payload.get("local_models", []):
            models.append(self._parse(item, source="local"))
        for item in payload.get("api_models", []):
            models.append(self._parse(item, source="api"))
        return models

    async def generate(
        self,
        *,
        prompt: str,
        model: str = "fast",
        duration: int = 5,
        resolution: str = "1080p",
        fps: int = 24,
        audio: bool = False,
        negative_prompt: str = "",
        image_path: str | None = None,
        aspect_ratio: Literal["16:9", "9:16"] = "16:9",
        camera_motion: str = "none",
        timeout: float = _GENERATION_TIMEOUT_S,
    ) -> str:
        """Generate one clip via ``POST /api/generate`` and return its file path.

        Text-to-video by default; passing ``image_path`` switches LTX-Desktop to
        image-to-video (it seeds generation from that frame). The call blocks
        until the app finishes, then returns the local ``video_path`` it wrote.

        Raises ``ProviderQuotaError`` when LTX cloud credits are exhausted (HTTP
        402) and ``ProviderError`` on any other failure or a cancelled job.
        """
        body: dict[str, Any] = {
            "prompt": prompt,
            "model": model,
            "duration": _clamp_duration(duration),
            "resolution": resolution,
            "fps": fps,
            "audio": audio,
            "negativePrompt": negative_prompt,
            "aspectRatio": aspect_ratio,
            "cameraMotion": camera_motion,
        }
        if image_path is not None:
            body["imagePath"] = image_path
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/generate", json=body, headers=self._headers
                )
            if resp.status_code == HTTPStatus.PAYMENT_REQUIRED:
                raise ProviderQuotaError("LTX-Desktop: insufficient LTX API credits")
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"LTX-Desktop generation failed: {exc}") from exc
        if payload.get("status") != "complete":
            raise ProviderError(f"LTX-Desktop generation {payload.get('status', 'failed')}")
        video_path = payload.get("video_path")
        if not video_path:
            raise ProviderError("LTX-Desktop completed but returned no video_path")
        return str(video_path)

    @staticmethod
    def _parse(item: dict[str, Any], *, source: Literal["local", "api"]) -> LtxModel:
        spec = item.get("spec", {}) or {}
        res_map: dict[str, Any] = spec.get("supported_resolutions_durations", {}) or {}
        resolutions = tuple(res_map.keys())
        max_duration = 0
        for res_spec in res_map.values():
            for durations in (res_spec or {}).get("fps_to_durations", {}).values():
                for d in durations or []:
                    max_duration = max(max_duration, int(d))
        return LtxModel(
            id=str(item.get("pipeline", "")),
            display_name=str(spec.get("display_name") or item.get("pipeline", "")),
            source=source,
            resolutions=resolutions,
            max_duration_s=max_duration,
        )


class LtxDesktopProvider:
    """`VideoProviderPort` adapter rendering clips through the LTX-Desktop app.

    Generation runs locally (or via LTX cloud) inside the app and writes a file
    on disk; this adapter reads that file and stores it under ``episode-artifacts``
    so the unified render pipeline treats LTX exactly like any other provider.
    Reference images switch it to image-to-video for character consistency.
    """

    name = "ltx"

    def __init__(
        self,
        settings: Settings,
        storage: StoragePort,
        *,
        client: LtxDesktopClient | None = None,
        model: str = "fast",
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._client = client or LtxDesktopClient(settings.ltx_desktop_url)
        self._model = model
        self._resolution = "1080p"

    def with_context(self, *, prefer_models: tuple[str, ...] = (), **_: Any) -> LtxDesktopProvider:
        """Bind the chosen model (from routing hints); ignore the rest. Fluent."""
        if prefer_models:
            self._model = prefer_models[0]
        return self

    async def generate_clip(
        self,
        prompt: ScenePrompt,
        refs: Iterable[ImageRef],
        seed: int | None = None,
    ) -> ClipArtifact:
        ref_list = list(refs)
        image_path: str | None = None
        if ref_list:
            bucket, _, key = ref_list[0].storage_key.partition("/")
            image_path = str(await self._storage.open_path(bucket, key))

        video_path = await self._client.generate(
            prompt=prompt.visual_prompt,
            model=self._model,
            duration=max(1, round(prompt.duration_s)),
            resolution=self._resolution,
            negative_prompt=prompt.negative_prompt or "",
            image_path=image_path,
            audio=True,
        )
        data = Path(video_path).read_bytes()
        storage_key = await self._storage.put(
            CLIP_BUCKET, f"{self.name}/{uuid.uuid4().hex}.mp4", data
        )
        width, height = _RESOLUTION_WH.get(self._resolution, (1920, 1080))
        return ClipArtifact(
            storage_key=storage_key,
            duration_s=prompt.duration_s,
            width=width,
            height=height,
            provider_name=self.name,
            provider_model=self._model,
            seed=seed,
        )

    async def extend_clip(self, clip: ClipArtifact, prompt: ScenePrompt) -> ClipArtifact:
        # LTX-Desktop has no extend endpoint; the pipeline uses jump-to-scene
        # (image-to-video from the last frame) instead — handled at the pipeline
        # level, not here.
        raise ProviderError("ltx extend_clip is not supported (use jump-to-scene)")

    async def availability(self) -> ProviderHealth:
        if not await self._client.is_up():
            return ProviderHealth(
                available=False, name=self.name,
                message=f"LTX-Desktop no responde en {self._settings.ltx_desktop_url}",
            )
        try:
            models = await self._client.list_models()
        except httpx.HTTPError as exc:
            return ProviderHealth(available=True, name=self.name, message=str(exc))
        return ProviderHealth(
            available=True, name=self.name,
            message=f"{len(models)} modelos disponibles",
        )


__all__ = ["LtxDesktopClient", "LtxDesktopProvider", "LtxModel"]
