"""ArtlistProvider — single API key fronting many video models.

Artlist.io aggregates Kling 3.0, Veo 2, Luma Dream Machine, MiniMax Hailuo and
PixVerse behind one account. This adapter loads the live model catalog (cached),
delegates the "which engine?" decision to the pure `ArtlistModelSelector`, then
submits/polls/stores the result — all behind the standard `VideoProviderPort`,
so the rest of the system never learns a model swap happened underneath.
"""
from __future__ import annotations

import time
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any

import httpx

from videocreator.domain.ports import StoragePort
from videocreator.domain.services.artlist_model_selector import ArtlistModelSelector
from videocreator.domain.value_objects import (
    Capability,
    ClipArtifact,
    ImageRef,
    LatencyPriority,
    ModelFamily,
    ModelHandle,
    ProviderHealth,
    ScenePrompt,
    StyleProfile,
)
from videocreator.infrastructure.providers.base import BaseHttpVideoProvider
from videocreator.shared.config import Settings
from videocreator.shared.errors import (
    ArtlistTimeoutError,
    ProviderError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# Fallback catalog used when the live `/v1/models` endpoint is unreachable, so
# selection logic (and tests) have something deterministic to reason over.
_STATIC_CATALOG: tuple[ModelHandle, ...] = (
    ModelHandle(
        id="kling-3.0",
        family="kling",
        capabilities=frozenset(
            {
                Capability.TEXT_TO_VIDEO,
                Capability.IMAGE_TO_VIDEO,
                Capability.REF_IMAGE,
                Capability.CAMERA_CONTROL,
            }
        ),
        max_duration_s=10,
        max_resolution=(1920, 1080),
        cost_per_second_usd=0.18,
        latency_p95_s=70,
        strengths=("photoreal", "stable_face", "motion"),
    ),
    ModelHandle(
        id="veo-2",
        family="veo",
        capabilities=frozenset(
            {Capability.TEXT_TO_VIDEO, Capability.IMAGE_TO_VIDEO, Capability.AUDIO_SYNC}
        ),
        max_duration_s=8,
        max_resolution=(1920, 1080),
        cost_per_second_usd=0.25,
        latency_p95_s=90,
        strengths=("photoreal", "cinematic"),
    ),
    ModelHandle(
        id="luma-dream",
        family="luma",
        capabilities=frozenset({Capability.TEXT_TO_VIDEO, Capability.EXTEND}),
        max_duration_s=9,
        max_resolution=(1280, 720),
        cost_per_second_usd=0.12,
        latency_p95_s=55,
        strengths=("dreamy", "fast_motion"),
    ),
    ModelHandle(
        id="minimax-hailuo",
        family="minimax",
        capabilities=frozenset({Capability.TEXT_TO_VIDEO}),
        max_duration_s=6,
        max_resolution=(1280, 720),
        cost_per_second_usd=0.08,
        latency_p95_s=45,
        strengths=("cheap", "stock_montage"),
    ),
    ModelHandle(
        id="pixverse-v3",
        family="pixverse",
        capabilities=frozenset({Capability.TEXT_TO_VIDEO, Capability.IMAGE_TO_VIDEO}),
        max_duration_s=8,
        max_resolution=(1280, 720),
        cost_per_second_usd=0.10,
        latency_p95_s=50,
        strengths=("anime", "fast_motion"),
    ),
)


class ArtlistProvider(BaseHttpVideoProvider):
    """`VideoProviderPort` adapter that sub-routes across Artlist's models."""

    name = "artlist"

    def __init__(
        self,
        settings: Settings,
        storage: StoragePort,
        selector: ArtlistModelSelector | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = settings.artlist_base_url
        super().__init__(settings, storage, max_concurrency=3, **kwargs)
        self._selector = selector or ArtlistModelSelector()
        self._catalog: list[ModelHandle] | None = None
        self._catalog_loaded_at: float = 0.0
        self._ttl = settings.artlist_catalog_ttl_seconds
        # Per-pod routing context (bind via `with_context` before generating).
        self._style: StyleProfile = StyleProfile.CINEMATIC_3D
        self._budget_usd: float | None = None
        self._latency_priority: LatencyPriority = "balanced"
        self._prefer_models: tuple[str, ...] = ()

    # ---- transport --------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        token = self._settings.artlist_api_token
        if not token:
            raise ProviderUnavailableError("ARTLIST_API_TOKEN is not configured")
        return {"Authorization": f"Bearer {token}", "accept": "application/json"}

    # ---- catalog ----------------------------------------------------------
    async def catalog(self, *, force_refresh: bool = False) -> list[ModelHandle]:
        """Return the model catalog, refreshing past TTL. Falls back to static."""
        fresh = (time.monotonic() - self._catalog_loaded_at) < self._ttl
        if self._catalog is not None and fresh and not force_refresh:
            return self._catalog
        try:
            self._catalog = await self._fetch_catalog()
        except (httpx.HTTPError, ProviderError) as exc:
            log.warning("artlist.catalog.fallback", error=str(exc))
            self._catalog = list(_STATIC_CATALOG)
        self._catalog_loaded_at = time.monotonic()
        return self._catalog

    async def _fetch_catalog(self) -> list[ModelHandle]:
        resp = await self._http().get("/v1/models")
        resp.raise_for_status()
        rows = resp.json().get("models", [])
        return [self._parse_model(row) for row in rows] or list(_STATIC_CATALOG)

    @staticmethod
    def _parse_model(row: dict[str, Any]) -> ModelHandle:
        caps = frozenset(
            Capability(c) for c in row.get("capabilities", []) if c in Capability._value2member_map_
        )
        family: ModelFamily = row.get("family", "other")
        res = row.get("max_resolution", [1920, 1080])
        return ModelHandle(
            id=row["id"],
            family=family,
            capabilities=caps,
            max_duration_s=int(row.get("max_duration_s", 5)),
            max_resolution=(int(res[0]), int(res[1])),
            cost_per_second_usd=float(row.get("cost_per_second_usd", 0.0)),
            latency_p95_s=int(row.get("latency_p95_s", 60)),
            strengths=tuple(row.get("strengths", [])),
        )

    # ---- VideoProviderPort ------------------------------------------------
    async def generate_clip(
        self,
        prompt: ScenePrompt,
        refs: Iterable[ImageRef],
        seed: int | None = None,
    ) -> ClipArtifact:
        ref_list = list(refs)
        catalog = await self.catalog()
        required: frozenset[Capability] = (
            frozenset({Capability.IMAGE_TO_VIDEO, Capability.REF_IMAGE})
            if ref_list
            else frozenset({Capability.TEXT_TO_VIDEO})
        )
        model = self._selector.select(
            catalog,
            style_profile=self._style,
            duration_s=prompt.duration_s,
            budget_usd=self._budget_usd,
            latency_priority=self._latency_priority,
            prefer_models=self._prefer_models,
            required=required,
        )
        log.info("artlist.model.selected", model=model.id, family=model.family)

        body = self._build_request_body(prompt, ref_list, model, seed)
        async with self._semaphore:
            job_id = await self._submit(body)
            payload = await self._poll_until_done(
                f"/v1/generations/{job_id}",
                is_done=lambda p: p.get("status") in {"succeeded", "completed"},
                is_failed=lambda p: p.get("status") in {"failed", "error", "cancelled"},
            )
        url = payload.get("output_url") or payload.get("video_url")
        if not url:
            raise ProviderError("artlist completed job has no output url")
        data = await self._download(str(url))
        return await self._store_clip(
            data,
            key=f"{self.name}/{model.id}/{job_id}.mp4",
            duration_s=float(payload.get("duration_s", prompt.duration_s)),
            width=model.max_resolution[0],
            height=model.max_resolution[1],
            model=model.id,
            seed=seed,
        )

    async def extend_clip(self, clip: ClipArtifact, prompt: ScenePrompt) -> ClipArtifact:
        raise ProviderError(f"{self.name} extend_clip routing not implemented yet")

    async def availability(self) -> ProviderHealth:
        if not self._settings.artlist_api_token:
            return ProviderHealth(
                available=False, name=self.name, message="ARTLIST_API_TOKEN not configured"
            )
        try:
            models = await self.catalog(force_refresh=True)
        except httpx.HTTPError as exc:
            return ProviderHealth(available=False, name=self.name, message=str(exc))
        cheapest = min((m.cost_per_second_usd for m in models), default=None)
        return ProviderHealth(
            available=True,
            name=self.name,
            message=f"{len(models)} models available",
            cost_per_second_usd=cheapest,
        )

    # ---- per-pod context (set by container/use-case before generate) ------
    def with_context(
        self,
        *,
        style_profile: StyleProfile,
        budget_usd: float | None,
        latency_priority: LatencyPriority,
        prefer_models: tuple[str, ...],
    ) -> ArtlistProvider:
        """Bind per-pod routing context. Returns self for fluent use."""
        self._style = style_profile
        self._budget_usd = budget_usd
        self._latency_priority = latency_priority
        self._prefer_models = prefer_models
        return self

    # ---- vendor shaping ---------------------------------------------------
    def _build_request_body(
        self, prompt: ScenePrompt, refs: list[ImageRef], model: ModelHandle, seed: int | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model.id,
            "prompt": prompt.visual_prompt,
            "duration_seconds": prompt.duration_s,
        }
        if prompt.negative_prompt:
            body["negative_prompt"] = prompt.negative_prompt
        if refs:
            body["reference_image_keys"] = [r.storage_key for r in refs]
        if seed is not None:
            body["seed"] = seed
        return body

    async def _submit(self, body: dict[str, Any]) -> str:
        try:
            resp = await self._http().post("/v1/generations", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                raise ProviderQuotaError(f"{self.name} quota exceeded") from exc
            if exc.response.status_code in {HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.GATEWAY_TIMEOUT}:
                raise ArtlistTimeoutError(f"{self.name} gateway timeout") from exc
            raise ProviderError(
                f"{self.name} HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        job_id = resp.json().get("id") or resp.json().get("job_id")
        if not job_id:
            raise ProviderError(f"{self.name} did not return a generation id")
        return str(job_id)


__all__ = ["ArtlistProvider"]
