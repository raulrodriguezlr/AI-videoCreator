"""Dummy adapter for integration tests."""
from __future__ import annotations

import pathlib

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)


class Adapter(AdapterBase):
    """Returns a dummy video for testing."""

    async def generate(self, request: GenRequest) -> GenResult:
        dummy_path = pathlib.Path(__file__).parent / "dummy.mp4"
        video_bytes = dummy_path.read_bytes() if dummy_path.exists() else b"\x00"

        return GenResult(
            video_bytes=video_bytes,
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id="test-model-v1",
            seed=request.seed,
            has_audio=False,
        )
