"""Tests for SdkImageProvider — the ImageGenerationPort over an SDK adapter.

A fake registry/adapter stands in for the real Higgsfield provider so we assert
the bridge (GenRequest in, list[bytes] out) without any network.
"""
from __future__ import annotations

import pytest

from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest, GenResult
from videocreator.infrastructure.providers.sdk_image_provider import SdkImageProvider
from videocreator.shared.errors import ProviderError, ProviderUnavailableError


class _FakeAdapter:
    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.requests: list[GenRequest] = []

    async def generate(self, request: GenRequest) -> GenResult:
        self.requests.append(request)
        return GenResult(video_bytes=self.blob, duration_s=0.0, width=1024,
                         height=1024, model_id=request.model_id, has_audio=False)


class _FakeLoaded:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter


class _FakeRegistry:
    def __init__(self, loaded: object | None) -> None:
        self._loaded = loaded

    def get(self, provider_id: str) -> object | None:
        del provider_id
        return self._loaded


async def test_generate_bridges_adapter_bytes() -> None:
    adapter = _FakeAdapter(b"img-bytes")
    prov = SdkImageProvider(_FakeRegistry(_FakeLoaded(adapter)), "higgsfield", "soul")

    out = await prov.generate("a fox", width=512, height=768, num_images=2)

    assert out == [b"img-bytes", b"img-bytes"]  # one blob per requested image
    assert [r.model_id for r in adapter.requests] == ["soul", "soul"]
    assert adapter.requests[0].prompt == "a fox"
    assert (adapter.requests[0].width, adapter.requests[0].height) == (512, 768)


async def test_missing_provider_raises_unavailable() -> None:
    prov = SdkImageProvider(_FakeRegistry(None), "higgsfield", "soul")
    with pytest.raises(ProviderUnavailableError, match="not available"):
        await prov.generate("x")


async def test_empty_bytes_raises_provider_error() -> None:
    prov = SdkImageProvider(_FakeRegistry(_FakeLoaded(_FakeAdapter(b""))), "higgsfield", "soul")
    with pytest.raises(ProviderError, match="no image data"):
        await prov.generate("x")
