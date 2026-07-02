"""Production image-to-video / video-to-video continuation for Alternate-Ending.

`ProviderI2VContinuation` satisfies BOTH the `I2VContinuation` and `V2VContinuation`
protocols (application/use_cases/alternate_ending.py): called with `seed_frame=`
it resolves an `image_to_video` provider and seeds the still frame as the init
image (`mode="i2v"`); called with `video=` it resolves a `video_to_video`
EDITING provider (e.g. Gemini Omni Flash) and feeds it the real tail clip
(`mode="edit"`). Either way the generated tail clip is written to disk. This is
the single paid step; it is isolated here so the ffmpeg pipeline stays testable
with a fake (see test_alternate_ending.py).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class ProviderI2VContinuation:
    """Callable matching both the `I2VContinuation` and `V2VContinuation`
    protocols, backed by the SDK provider registry."""

    def __init__(self, registry: Any, *, model: str | None = None, provider: str | None = None) -> None:
        self._registry = registry
        self._model = model
        self._provider = provider

    def __call__(
        self, *, seed_frame: Path | None = None, video: Path | None = None,
        prompt: str, duration_s: float, out: Path,
    ) -> Path:
        # AlternateEndingService.run is sync (driven via asyncio.to_thread); the
        # provider adapter is async, so spin a loop inside this worker thread.
        return asyncio.run(self._generate(seed_frame, video, prompt, duration_s, out))

    async def _generate(
        self, seed_frame: Path | None, video: Path | None,
        prompt: str, duration_s: float, out: Path,
    ) -> Path:
        if video is not None:
            # Pass the path string, not bytes — CLI-backed providers (Higgsfield)
            # need a file path for --video; passing raw bytes produces a str()
            # blob that exceeds Windows CreateProcess limits.
            return await self._run(
                "video_to_video",
                {"input_video": str(video), "input_video_path": str(video)},
                prompt, duration_s, out, log_prefix="v2v",
            )
        if seed_frame is not None:
            # Same rationale as above, mirrored for the i2v seed image. API-
            # backed providers that need bytes can read the file themselves via
            # the "input_image_path" key.
            return await self._run(
                "image_to_video",
                {"input_image": str(seed_frame), "input_image_path": str(seed_frame)},
                prompt, duration_s, out, log_prefix="i2v",
            )
        raise ProviderError("ProviderI2VContinuation requires either 'seed_frame' or 'video'")

    async def _run(
        self, capability: str, extra: dict[str, str], prompt: str, duration_s: float,
        out: Path, *, log_prefix: str,
    ) -> Path:
        from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest

        candidates = self._registry.find(capability)
        if not candidates:
            raise ProviderError(
                f"no provider declares '{capability}' — install one (providers.d)"
            )
        if self._provider:
            chosen = [lp for lp in candidates if lp.manifest.id == self._provider]
            if chosen:
                candidates = chosen + [lp for lp in candidates if lp.manifest.id != self._provider]
        request = GenRequest(
            prompt=prompt, duration_s=duration_s, model_id=self._model, extra=extra,
        )
        last_error: Exception | None = None
        for lp in candidates:
            try:
                result = await lp.adapter.generate(request)
                if not result.video_bytes:
                    raise ProviderError("provider returned no video bytes")
                out.write_bytes(result.video_bytes)
                log.info(f"alt_ending.{log_prefix}.done", provider=lp.manifest.id, out=str(out))
                return out
            except Exception as e:  # try the next provider in the chain
                last_error = e
                log.warning(f"alt_ending.{log_prefix}.failed", provider=lp.manifest.id, error=str(e))
        raise ProviderError(f"all {capability} providers failed: {last_error}")


__all__ = ["ProviderI2VContinuation"]
