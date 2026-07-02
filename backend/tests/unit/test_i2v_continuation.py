"""Tests for ProviderI2VContinuation (infrastructure/publish/i2v_continuation.py).

Covers the Fase 1 v2v extension: called with `video=` it must resolve a
`video_to_video` provider and pass `input_video`/`input_video_path` in extra
(mirroring the existing `input_image`/`input_image_path` dual-write); called
with `seed_frame=` it keeps the original `image_to_video` behaviour. No real
network/CLI — the registry and adapter are fakes. `ProviderI2VContinuation.
__call__` runs its own event loop internally (`asyncio.run`), so these tests
call it as a plain sync function — never from inside an async test.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from videocreator.infrastructure.publish.i2v_continuation import ProviderI2VContinuation
from videocreator.shared.errors import ProviderError


class _FakeGenResult:
    def __init__(self, video_bytes: bytes = b"OK") -> None:
        self.video_bytes = video_bytes


class _FakeAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.received: Any = None

    async def generate(self, request: Any) -> _FakeGenResult:
        self.received = request
        if self._fail:
            raise RuntimeError("boom")
        return _FakeGenResult()


class _FakeLoaded:
    def __init__(self, pid: str, *, fail: bool = False) -> None:
        self.manifest = type("M", (), {"id": pid})()
        self.adapter = _FakeAdapter(fail=fail)


class _FakeRegistry:
    def __init__(self, by_capability: dict[str, list[_FakeLoaded]]) -> None:
        self._by_capability = by_capability

    def find(self, capability: str, **_: Any) -> list[_FakeLoaded]:
        return self._by_capability.get(capability, [])


class TestVideoToVideoMode:
    def test_video_kwarg_resolves_video_to_video_and_sets_extra(self, tmp_path: Path) -> None:
        higgs = _FakeLoaded("higgsfield")
        registry = _FakeRegistry({"video_to_video": [higgs]})
        cont = ProviderI2VContinuation(registry)
        clip = tmp_path / "tail_src.mp4"
        clip.write_bytes(b"x")
        out = tmp_path / "tail.mp4"

        result = cont(video=clip, prompt="add rain", duration_s=3.0, out=out)

        assert result == out
        assert out.read_bytes() == b"OK"
        req = higgs.adapter.received
        assert req.extra["input_video"] == str(clip)
        assert req.extra["input_video_path"] == str(clip)

    def test_no_video_to_video_provider_raises(self, tmp_path: Path) -> None:
        registry = _FakeRegistry({})
        cont = ProviderI2VContinuation(registry)
        with pytest.raises(ProviderError, match="video_to_video"):
            cont(video=tmp_path / "x.mp4", prompt="x", duration_s=3.0, out=tmp_path / "out.mp4")


class TestImageToVideoMode:
    def test_seed_frame_kwarg_resolves_image_to_video_and_sets_extra(self, tmp_path: Path) -> None:
        wan = _FakeLoaded("wan")
        registry = _FakeRegistry({"image_to_video": [wan]})
        cont = ProviderI2VContinuation(registry)
        seed = tmp_path / "seed.png"
        seed.write_bytes(b"x")
        out = tmp_path / "tail.mp4"

        result = cont(seed_frame=seed, prompt="x", duration_s=5.0, out=out)

        assert result == out
        req = wan.adapter.received
        assert req.extra["input_image"] == str(seed)
        assert req.extra["input_image_path"] == str(seed)


class TestProviderPreference:
    def test_requested_provider_goes_first(self, tmp_path: Path) -> None:
        bad = _FakeLoaded("bad", fail=True)
        good = _FakeLoaded("good")
        registry = _FakeRegistry({"video_to_video": [bad, good]})
        cont = ProviderI2VContinuation(registry, provider="good")
        out = tmp_path / "tail.mp4"

        cont(video=tmp_path / "src.mp4", prompt="x", duration_s=3.0, out=out)

        # "good" was requested, so it should go first and succeed without
        # ever falling through to "bad".
        assert good.adapter.received is not None
        assert bad.adapter.received is None

    def test_falls_back_on_failure(self, tmp_path: Path) -> None:
        bad = _FakeLoaded("bad", fail=True)
        good = _FakeLoaded("good")
        registry = _FakeRegistry({"video_to_video": [bad, good]})
        cont = ProviderI2VContinuation(registry)
        out = tmp_path / "tail.mp4"

        result = cont(video=tmp_path / "src.mp4", prompt="x", duration_s=3.0, out=out)

        assert result == out
        assert bad.adapter.received is not None
        assert good.adapter.received is not None


def test_neither_kwarg_raises() -> None:
    cont = ProviderI2VContinuation(_FakeRegistry({}))
    with pytest.raises(ProviderError, match="seed_frame' or 'video'"):
        cont(prompt="x", duration_s=1.0, out=Path("out.mp4"))
