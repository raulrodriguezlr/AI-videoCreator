"""ElevenLabsStudioProvider — ElevenLabs Studio 3.0 (text/image → video).

Distinct from the classic ElevenLabs TTS provider: Studio 3.0 is the multimodal
long-form suite that can emit voice + video in a single job (native lipsync),
which makes it the natural fit for `style_profile = talking_head_avatar`.

The exact Studio REST contract is still firming up upstream, so request/response
shaping is centralised in the small private helpers below — when the live API
shape is confirmed, only those need to change.
"""
from __future__ import annotations

from collections.abc import Iterable
from http import HTTPStatus
from typing import Any

import httpx

from videocreator.domain.ports import StoragePort
from videocreator.domain.value_objects import ClipArtifact, ImageRef, ProviderHealth, ScenePrompt
from videocreator.infrastructure.providers.base import BaseHttpVideoProvider
from videocreator.shared.config import Settings
from videocreator.shared.errors import (
    ElevenLabsStudioQuotaError,
    ElevenLabsStudioSafetyError,
    ProviderError,
    ProviderUnavailableError,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_DEFAULT_COST_PER_SECOND_USD = 0.30


class ElevenLabsStudioProvider(BaseHttpVideoProvider):
    """`VideoProviderPort` adapter backed by ElevenLabs Studio 3.0."""

    name = "elevenlabs_studio"
    base_url = "https://api.elevenlabs.io"

    def __init__(self, settings: Settings, storage: StoragePort, **kwargs: Any) -> None:
        super().__init__(settings, storage, max_concurrency=2, **kwargs)
        self._model_id = settings.elevenlabs_studio_model_id
        self._tier = settings.elevenlabs_studio_tier

    # ---- transport --------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        key = self._settings.elevenlabs_api_key
        if not key:
            raise ProviderUnavailableError("ELEVENLABS_API_KEY is not configured")
        return {"xi-api-key": key, "accept": "application/json"}

    # ---- VideoProviderPort ------------------------------------------------
    async def generate_clip(
        self,
        prompt: ScenePrompt,
        refs: Iterable[ImageRef],
        seed: int | None = None,
    ) -> ClipArtifact:
        ref_list = list(refs)
        body = self._build_request_body(prompt, ref_list, seed)
        async with self._semaphore:
            job_id = await self._submit(body)
            payload = await self._poll_until_done(
                f"/v1/studio/jobs/{job_id}",
                is_done=lambda p: p.get("status") == "completed",
                is_failed=lambda p: p.get("status") in {"failed", "error"},
            )
        url = self._extract_output_url(payload)
        data = await self._download(url)
        width, height = self._resolution(payload)
        return await self._store_clip(
            data,
            key=f"{self.name}/{job_id}.mp4",
            duration_s=float(payload.get("duration_s", prompt.duration_s)),
            width=width,
            height=height,
            model=self._model_id,
            seed=seed,
            has_audio=bool(prompt.audio_text),
        )

    async def extend_clip(self, clip: ClipArtifact, prompt: ScenePrompt) -> ClipArtifact:
        # Studio has no first-class extend yet; surface this clearly.
        raise ProviderError(f"{self.name} does not support extend_clip")

    async def availability(self) -> ProviderHealth:
        if not self._settings.elevenlabs_api_key:
            return ProviderHealth(
                available=False, name=self.name, message="ELEVENLABS_API_KEY not configured"
            )
        try:
            resp = await self._http().get("/v1/user")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(available=False, name=self.name, message=str(exc))
        return ProviderHealth(
            available=True,
            name=self.name,
            message=f"tier={self._tier} model={self._model_id}",
            cost_per_second_usd=_DEFAULT_COST_PER_SECOND_USD,
        )

    # ---- vendor shaping (the only API-coupled bits) -----------------------
    def _build_request_body(
        self, prompt: ScenePrompt, refs: list[ImageRef], seed: int | None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model_id": self._model_id,
            "prompt": prompt.visual_prompt,
            "duration_seconds": prompt.duration_s,
        }
        if prompt.negative_prompt:
            body["negative_prompt"] = prompt.negative_prompt
        if prompt.audio_text:
            # Studio's edge: voice + video lipsync in a single job.
            body["dub_inline"] = {"script": prompt.audio_text}
        if refs:
            body["reference_image_keys"] = [r.storage_key for r in refs]
        if seed is not None:
            body["seed"] = seed
        return body

    async def _submit(self, body: dict[str, Any]) -> str:
        try:
            resp = await self._http().post("/v1/studio/jobs", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._classify(exc) from exc
        job_id = resp.json().get("job_id")
        if not job_id:
            raise ProviderError(f"{self.name} did not return a job_id")
        return str(job_id)

    @staticmethod
    def _extract_output_url(payload: dict[str, Any]) -> str:
        url = payload.get("output_url") or payload.get("video_url")
        if not url:
            raise ProviderError("elevenlabs_studio completed job has no output url")
        return str(url)

    @staticmethod
    def _resolution(payload: dict[str, Any]) -> tuple[int, int]:
        res = payload.get("resolution") or {}
        return int(res.get("width", 1920)), int(res.get("height", 1080))

    def _classify(self, exc: httpx.HTTPStatusError) -> ProviderError:
        status = exc.response.status_code
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            return ElevenLabsStudioQuotaError(f"{self.name} quota exceeded")
        if status in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY}:
            body = exc.response.text.lower()
            if "safety" in body or "moderation" in body:
                return ElevenLabsStudioSafetyError(f"{self.name} rejected by safety filter")
        return ProviderError(f"{self.name} HTTP {status}: {exc.response.text[:200]}")


__all__ = ["ElevenLabsStudioProvider"]
