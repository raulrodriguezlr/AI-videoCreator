"""Veo via Gemini API — minimal SDK adapter (text_to_video).

Uses google-genai directly: generate_videos → poll operation → download bytes.
Gemini API serves ONLY `-preview` Veo ids; Vertex is a separate provider.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.shared.config import get_settings
from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_POLL_INTERVAL_S = 10.0


class Adapter(AdapterBase):
    def _client(self) -> Any:
        try:
            from google import genai  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderError("google-genai not installed") from e
        api_key = get_settings().google_api_key
        if not api_key:
            raise ProviderError("GOOGLE_API_KEY not configured")
        return genai.Client(api_key=api_key)

    async def generate(self, request: GenRequest) -> GenResult:
        model = request.model_id or get_settings().veo_model
        return await asyncio.to_thread(self._generate_sync, request, model)

    def _generate_sync(self, request: GenRequest, model: str) -> GenResult:
        from google.genai import types  # type: ignore[import-untyped]

        client = self._client()
        aspect = "9:16" if request.height > request.width else "16:9"
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect,
            negative_prompt=request.negative_prompt,
        )
        operation = client.models.generate_videos(
            model=model, prompt=request.prompt, config=config,
        )
        timeout_s = self.manifest.latency.timeout_s
        elapsed = 0.0
        while not operation.done:
            if elapsed >= timeout_s:
                raise ProviderError(f"veo-gemini timed out after {timeout_s}s")
            time.sleep(_POLL_INTERVAL_S)
            elapsed += _POLL_INTERVAL_S
            operation = client.operations.get(operation=operation)

        response = getattr(operation, "response", None)
        videos = getattr(response, "generated_videos", None) if response else None
        if not videos:
            filtered = getattr(response, "rai_media_filtered_reasons", None)
            raise ProviderError(
                f"veo-gemini returned no video (model={model}, "
                f"rai={filtered or 'n/a'})"
            )
        video = videos[0].video
        client.files.download(file=video)
        data = video.video_bytes
        if not data:
            raise ProviderError("veo-gemini download produced no bytes")
        log.info("veo_gemini.done", model=model, size=len(data))
        w, h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
        return GenResult(
            video_bytes=data,
            duration_s=min(request.duration_s, 8.0),
            width=w,
            height=h,
            model_id=model,
            seed=request.seed,
            has_audio=True,
        )
