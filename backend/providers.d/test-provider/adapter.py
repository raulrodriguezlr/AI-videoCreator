"""Dummy adapter for integration tests."""
from __future__ import annotations

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)


import pathlib

class Adapter(AdapterBase):
    """Returns a dummy video for testing."""

    async def generate(self, request: GenRequest) -> GenResult:
        dummy_path = pathlib.Path(__file__).parent / "dummy.mp4"
        if dummy_path.exists():
            video_bytes = dummy_path.read_bytes()
        else:
            video_bytes = b"\x00"
            
        return GenResult(
            video_bytes=video_bytes,
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id="test-model-v1",
            seed=request.seed,
            has_audio=False,
        )
