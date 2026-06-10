"""Dummy adapter for integration tests."""
from __future__ import annotations

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)


class Adapter(AdapterBase):
    """Returns a 1-byte dummy video for testing."""

    async def generate(self, request: GenRequest) -> GenResult:
        return GenResult(
            video_bytes=b"\x00",
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id="test-model-v1",
            seed=request.seed,
            has_audio=False,
        )
