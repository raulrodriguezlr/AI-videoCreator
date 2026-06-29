"""Production image-to-video continuation for Alternate-Ending.

Resolves an `image_to_video` provider from the SDK registry, sends the seed
frame as the init image, and writes the generated tail clip to disk. This is the
single paid step; it is isolated here so the ffmpeg pipeline stays testable with
a fake (see test_alternate_ending.py).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class ProviderI2VContinuation:
    """Callable matching the `I2VContinuation` protocol, backed by the registry."""

    def __init__(self, registry: Any, *, model: str | None = None) -> None:
        self._registry = registry
        self._model = model

    def __call__(self, *, seed_frame: Path, prompt: str, duration_s: float, out: Path) -> Path:
        # AlternateEndingService.run is sync (driven via asyncio.to_thread); the
        # provider adapter is async, so spin a loop inside this worker thread.
        return asyncio.run(self._generate(seed_frame, prompt, duration_s, out))

    async def _generate(self, seed_frame: Path, prompt: str, duration_s: float, out: Path) -> Path:
        from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest

        candidates = self._registry.find("image_to_video")
        if not candidates:
            raise ProviderError(
                "no provider declares 'image_to_video' — install one (providers.d)"
            )
        request = GenRequest(
            prompt=prompt,
            duration_s=duration_s,
            model_id=self._model,
            extra={"input_image": seed_frame.read_bytes()},
        )
        last_error: Exception | None = None
        for lp in candidates:
            try:
                result = await lp.adapter.generate(request)
                if not result.video_bytes:
                    raise ProviderError("provider returned no video bytes")
                out.write_bytes(result.video_bytes)
                log.info("alt_ending.i2v.done", provider=lp.manifest.id, out=str(out))
                return out
            except Exception as e:  # try the next provider in the chain
                last_error = e
                log.warning("alt_ending.i2v.failed", provider=lp.manifest.id, error=str(e))
        raise ProviderError(f"all image_to_video providers failed: {last_error}")


__all__ = ["ProviderI2VContinuation"]
