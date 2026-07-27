"""Tests for the Higgsfield SDK adapter (providers.d/higgsfield/adapter.py).

The adapter is a file-based python plugin (loaded by the registry via
importlib), so we load it the same way here. No real network and no real CLI:
`_run` (the subprocess call to `hf`) and `_download` are replaced with fakes,
and the module's `get_settings` is monkeypatched.

Contract under test (verified against @higgsfield/cli v0.2.x):
`hf generate create <cli_type> --prompt "..." [flags] --json --wait`
→ JSON with `result_url` → download bytes. OAuth session spends PLUS credits.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest
from videocreator.infrastructure.providers.sdk.manifest import (
    AdapterSpec,
    LatencyProfile,
    ModelSpec,
    ProviderManifest,
)
from videocreator.shared.errors import HiggsfieldNeedsAuthError, ProviderError

ADAPTER_PATH = (
    Path(__file__).resolve().parents[2] / "providers.d" / "higgsfield" / "adapter.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("higgsfield_adapter_test", ADAPTER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> ProviderManifest:
    return ProviderManifest(
        id="higgsfield",
        name="Higgsfield",
        capabilities=["text_to_video", "image_to_video", "text_to_image"],
        latency=LatencyProfile(timeout_s=120),
        adapter=AdapterSpec(type="python", entrypoint="adapter.py"),
        models=[
            ModelSpec(id="soul", cli_type="text2image_soul_v2",
                      capabilities=["text_to_image"]),
            ModelSpec(id="wan-2.6", cli_type="wan2_6", backend="web",
                      capabilities=["text_to_video", "image_to_video"],
                      max_duration_s=15),
            ModelSpec(id="veo-web", cli_type="veo3_1", backend="web",
                      capabilities=["text_to_video", "image_to_video"],
                      max_duration_s=8, valid_durations=(4, 6, 8)),
            ModelSpec(id="no-cli", capabilities=["text_to_video"]),  # no cli_type
            ModelSpec(id="gemini-omni-flash", cli_type="gemini_omni",
                      capabilities=["video_to_video", "image_to_video", "text_to_video"],
                      max_duration_s=10, valid_durations=(4, 6, 8, 10)),
        ],
    )


def _adapter(mod, tmp_path: Path, *, cli="hf"):
    mod.get_settings = lambda: SimpleNamespace(higgsfield_cli_path=cli)  # type: ignore[attr-defined]
    return mod.Adapter(manifest=_manifest(), base_dir=tmp_path)


def _stub_io(adapter, *, stdout: str = "", code: int = 0, stderr: str = "",
             blob: bytes = b"HFBYTES") -> dict:
    """Replace the subprocess + download seams; capture the args used."""
    captured: dict = {}

    async def _run(args):
        captured["args"] = args
        return stdout, stderr, code

    async def _download(url):
        captured["url"] = url
        return blob

    adapter._run = _run            # type: ignore[method-assign]
    adapter._download = _download  # type: ignore[method-assign]
    return captured


# ---- Pure helpers ----------------------------------------------------------
class TestHelpers:
    def test_first_url_digs_known_paths(self) -> None:
        mod = _load_module()
        assert mod._first_url({"result_url": "https://a/b.mp4"}) == "https://a/b.mp4"
        assert mod._first_url({"results": [{"url": "https://a/c.png"}]}) == "https://a/c.png"
        # tolerant scan for a media-looking url nested anywhere
        assert mod._first_url({"x": {"y": "https://a/deep.webp"}}) == "https://a/deep.webp"
        assert mod._first_url({"status": "completed"}) is None

    def test_aspect_ratio(self) -> None:
        mod = _load_module()
        assert mod._aspect_ratio(1024, 1024) == "1:1"
        assert mod._aspect_ratio(1080, 1920) == "9:16"
        assert mod._aspect_ratio(1920, 1080) == "16:9"

    def test_parse_json_tolerates_progress_lines(self) -> None:
        mod = _load_module()
        out = 'submitting...\nrendering 50%\n{"result_url": "https://a/x.png"}'
        assert mod._parse_json(out) == {"result_url": "https://a/x.png"}

    def test_snap_duration(self) -> None:
        mod = _load_module()
        veo = SimpleNamespace(max_duration_s=8, valid_durations=(4, 6, 8))
        assert mod._snap_duration(3.5, veo) == 4
        assert mod._snap_duration(5, veo) == 6      # tie → longer
        assert mod._snap_duration(7, veo) == 8
        assert mod._snap_duration(8, veo) == 8
        # continuous model: clamp to max + round, no snap list
        wan = SimpleNamespace(max_duration_s=15, valid_durations=())
        assert mod._snap_duration(20, wan) == 15
        assert mod._snap_duration(6, wan) == 6


# ---- generate() ------------------------------------------------------------
class TestGenerate:
    @pytest.mark.asyncio
    async def test_image_builds_cli_args_and_returns_bytes(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/o.png"}),
                       blob=b"IMG")

        res = await adapter.generate(
            GenRequest(prompt="a fox", width=1024, height=1024, model_id="soul")
        )

        args = cap["args"]
        assert args[0] == "hf"
        assert args[1:4] == ["generate", "create", "text2image_soul_v2"]
        assert "--prompt" in args and "a fox" in args
        assert "--json" in args and "--wait" in args
        assert "--duration" not in args  # image, no duration
        assert res.video_bytes == b"IMG"
        assert res.has_audio is False
        assert res.metadata["transport"] == "cli"
        assert cap["url"] == "https://cdn.hf/o.png"

    @pytest.mark.asyncio
    async def test_video_includes_duration_and_start_image(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/v.mp4"}))

        res = await adapter.generate(GenRequest(
            prompt="char waving", duration_s=5, width=1080, height=1920,
            model_id="wan-2.6", extra={"input_image": "https://ref/c.png"},
        ))

        args = cap["args"]
        assert args[1:4] == ["generate", "create", "wan2_6"]
        assert "--duration" in args and "5" in args
        assert "--start-image" in args and "https://ref/c.png" in args
        assert "--aspect_ratio" in args and "9:16" in args
        assert res.has_audio is True

    @pytest.mark.asyncio
    async def test_video_to_video_uses_video_flag(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/edited.mp4"}))

        res = await adapter.generate(GenRequest(
            prompt="make it rain", duration_s=8, width=1080, height=1920,
            model_id="gemini-omni-flash", extra={"input_video": "/tmp/clip.mp4"},
        ))

        args = cap["args"]
        assert args[1:4] == ["generate", "create", "gemini_omni"]
        assert "--video" in args and "/tmp/clip.mp4" in args
        assert "--start-image" not in args
        assert res.has_audio is True

    @pytest.mark.asyncio
    async def test_input_video_wins_over_input_image_for_v2v_model(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/edited.mp4"}))

        await adapter.generate(GenRequest(
            prompt="x", duration_s=8, model_id="gemini-omni-flash",
            extra={"input_video": "/tmp/clip.mp4", "input_image": "https://ref/c.png"},
        ))

        args = cap["args"]
        assert "--video" in args and "/tmp/clip.mp4" in args
        assert "--start-image" not in args

    @pytest.mark.asyncio
    async def test_input_image_used_when_model_lacks_video_to_video(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/v.mp4"}))

        # wan-2.6 has no video_to_video capability — an input_video that snuck
        # into extra must not silently override the intended start-image.
        await adapter.generate(GenRequest(
            prompt="x", duration_s=5, model_id="wan-2.6",
            extra={"input_video": "/tmp/clip.mp4", "input_image": "https://ref/c.png"},
        ))

        args = cap["args"]
        assert "--start-image" in args and "https://ref/c.png" in args
        assert "--video" not in args

    @pytest.mark.asyncio
    async def test_video_snaps_duration_to_discrete_values(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        cap = _stub_io(adapter, stdout=json.dumps({"result_url": "https://cdn.hf/v.mp4"}))

        await adapter.generate(GenRequest(
            prompt="hero shot", duration_s=5, width=1920, height=1080, model_id="veo-web",
        ))

        args = cap["args"]
        di = args.index("--duration")
        # 5s is not a valid Veo length → must snap to 4 or 6, never send 5.
        assert args[di + 1] in {"4", "6"}
        # --resolution is never sent (CLI uses model's native resolution).
        assert "--resolution" not in args

    @pytest.mark.asyncio
    async def test_cli_nonzero_exit_raises(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        _stub_io(adapter, stdout="", code=1, stderr="Session expired")

        with pytest.raises(HiggsfieldNeedsAuthError):
            await adapter.generate(GenRequest(prompt="x", model_id="soul"))

    @pytest.mark.asyncio
    async def test_no_media_url_raises(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        _stub_io(adapter, stdout=json.dumps({"status": "completed"}))

        with pytest.raises(ProviderError, match="without a media URL"):
            await adapter.generate(GenRequest(prompt="x", model_id="soul"))

    @pytest.mark.asyncio
    async def test_model_without_cli_type_raises(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path)
        _stub_io(adapter)
        with pytest.raises(ProviderError, match="no `cli_type`"):
            await adapter.generate(GenRequest(prompt="x", model_id="no-cli"))

    @pytest.mark.asyncio
    async def test_cli_not_found_raises(self, tmp_path: Path) -> None:
        mod = _load_module()
        adapter = _adapter(mod, tmp_path, cli="definitely-not-a-real-binary-xyz")
        with pytest.raises(ProviderError, match="CLI not found"):
            await adapter.generate(GenRequest(prompt="x", model_id="soul"))
