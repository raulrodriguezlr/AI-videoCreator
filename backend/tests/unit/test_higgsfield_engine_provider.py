"""Tests for the HiggsfieldEngineProvider (legacy engine ↔ SDK adapter bridge).

Synchronous tests: the engine loop is sync and the provider drives the async SDK
adapter via `asyncio.run`, which must NOT run inside an already-running loop.
A fake adapter (returned from the module cache) stands in for the hf CLI.
"""
from __future__ import annotations

from pathlib import Path

from videocreator.infrastructure.engine import variables as engine_vars
from videocreator.infrastructure.engine.providers import (
    higgsfield_engine_provider as mod,
)
from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest, GenResult


class _FakeAdapter:
    def __init__(self, blob: bytes = b"MP4DATA") -> None:
        self.blob = blob
        self.requests: list[GenRequest] = []

    async def generate(self, request: GenRequest) -> GenResult:
        self.requests.append(request)
        return GenResult(video_bytes=self.blob, duration_s=request.duration_s,
                         width=1920, height=1080, model_id=request.model_id)


def _provider(tmp_path: Path, fake: _FakeAdapter, model: str = "kling-3.0"):
    mod._ADAPTER_CACHE["adapter"] = fake          # bypass real registry/CLI
    engine_vars.HIGGSFIELD_MODEL = model
    cfg = tmp_path / "config.json"
    cfg.write_text('{"series_name": "Test"}', encoding="utf-8")  # __init__ load_json
    return mod.HiggsfieldEngineProvider(str(cfg))


def test_generate_scene_writes_clip_and_uses_model(tmp_path: Path) -> None:
    fake = _FakeAdapter(b"HFCLIP")
    prov = _provider(tmp_path, fake, model="kling-3.0")
    clips = tmp_path / "clips"

    clip = prov.generate_scene(
        prompt="a fox runs", duration=5, save_dir=str(clips), scene_index=0,
    )

    # clip written where the pipeline expects it (clip_01.mp4)
    assert Path(clip.file_path).name == "clip_01.mp4"
    assert Path(clip.file_path).read_bytes() == b"HFCLIP"
    assert clip.duration == 5
    # the SDK request carried the chosen model + duration + prompt
    req = fake.requests[0]
    assert req.model_id == "kling-3.0"
    assert req.duration_s == 5.0
    assert req.prompt == "a fox runs"
    assert "input_image" not in req.extra  # text-to-video, no reference


def test_reference_image_becomes_input_image_non_kling(tmp_path: Path) -> None:
    # Non-Kling models use the reference as an image-to-video seed.
    fake = _FakeAdapter()
    prov = _provider(tmp_path, fake, model="wan-2.6")

    prov.generate_scene(
        prompt="char waves", duration=5, reference_images=["/path/ref.png"],
        save_dir=str(tmp_path / "clips"), scene_index=2,
    )

    assert fake.requests[0].extra["input_image"] == "/path/ref.png"


def test_kling_skips_reference_image(tmp_path: Path) -> None:
    # Kling treats input_image as a literal first frame → morphing. So a plain
    # reference image is NOT forwarded for kling models.
    fake = _FakeAdapter()
    prov = _provider(tmp_path, fake, model="kling-3.0")

    prov.generate_scene(
        prompt="char waves", duration=5, reference_images=["/path/ref.png"],
        save_dir=str(tmp_path / "clips"), scene_index=2,
    )

    assert "input_image" not in fake.requests[0].extra


def test_check_availability_reflects_cli_path(tmp_path: Path) -> None:
    prov = _provider(tmp_path, _FakeAdapter())
    # get_settings() returns the real Settings; cli path is set in this env/.env,
    # but the method must at least return a bool without raising.
    assert isinstance(prov.check_availability(), bool)
