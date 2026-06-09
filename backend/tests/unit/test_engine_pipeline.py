"""Guard rails for the shared engine Scene Builder pipeline.

The render engine has no behavioural unit tests (it shells out to ffmpeg / model
APIs), but these cheap structural checks lock in the unification invariants and
catch import-level regressions like a missing ``import time`` in the concat step
(which broke every multi-clip render).
"""
from __future__ import annotations

import inspect

from videocreator.infrastructure.engine.providers import base_provider
from videocreator.infrastructure.engine.providers.base_provider import BaseVideoProvider
from videocreator.infrastructure.engine.providers.http_cloud_providers import (
    ArtlistProvider,
    ElevenLabsStudioProvider,
)
from videocreator.infrastructure.engine.providers.ltx_desktop_provider import (
    LtxDesktopProvider,
)
from videocreator.infrastructure.engine.providers.ltx_provider import LtxProvider
from videocreator.infrastructure.engine.providers.veo_provider import VeoProvider

_ENGINE_PROVIDERS = (VeoProvider, LtxProvider, LtxDesktopProvider, ArtlistProvider, ElevenLabsStudioProvider)
# Orchestration hooks every provider must SHARE (identical behaviour).
_SHARED_HOOKS = (
    "generate_full_video",
    "_generate_clip",
    "_apply_dubbing",
    "_concatenate_clips",
    "_collect_reference_images",
    "_assemble_finals",
    "_build_cinematographic_prompt",
)


class _PromptStub(BaseVideoProvider):
    """Minimal concrete provider to exercise the shared prompt builder."""

    def __init__(self) -> None:
        self.config = {"characters": [{"name": "Tico", "voice_description": "cheerful"}]}

    def generate_scene(self, *a, **k): ...
    def extend_scene(self, *a, **k): ...
    def jump_to_scene(self, *a, **k): ...
    def check_availability(self): ...


def test_prompt_builder_injects_voice_for_lip_sync_dub() -> None:
    # Every provider must make the model GENERATE voice (so the STS dub can keep
    # lip-sync). The shared builder injects the spoken line + voice description,
    # and _sanitize_visual_prompt (a @staticmethod on the base — load-bearing for
    # the render) strips dialogue contamination from the visual prompt.
    assert hasattr(BaseVideoProvider, "_sanitize_visual_prompt")
    prompt = _PromptStub()._build_cinematographic_prompt(
        {"visual_prompt": 'a squirrel. The squirrel says "hi"',
         "character": "Tico", "audio_text": "Hola!"},
        "",
    )
    assert "Hola!" in prompt and "says" in prompt.lower()  # voice line present
    assert 'squirrel says "hi"' not in prompt  # contamination sanitised


def test_concat_module_imports_time() -> None:
    # Regression: _concatenate_clips uses int(time.time()); base must import time.
    assert hasattr(base_provider, "time")
    assert "time.time()" in inspect.getsource(BaseVideoProvider._concatenate_clips)


def test_all_engine_providers_share_the_orchestration() -> None:
    # Every provider inherits the SAME loop + hooks from the base — same dispatch,
    # dubbing, concat and reference collection. Only the model calls differ.
    for provider in _ENGINE_PROVIDERS:
        for hook in _SHARED_HOOKS:
            assert getattr(provider, hook) is getattr(BaseVideoProvider, hook), (
                f"{provider.__name__}.{hook} should be inherited from BaseVideoProvider"
            )


def test_providers_only_specialise_the_model_calls() -> None:
    # The atomic per-provider differences: how a clip is actually generated.
    # GPU/local providers (Veo, LTX, LTX-Desktop) override the methods directly;
    # HTTP cloud providers (Artlist, ElevenLabs) inherit from _HttpCloudVideoProvider
    # which provides shared submit→poll→download, and specialize via _build_body /
    # _auth_headers / check_availability.
    _LOCAL_PROVIDERS = (VeoProvider, LtxProvider, LtxDesktopProvider)
    for provider in _LOCAL_PROVIDERS:
        assert "generate_scene" in provider.__dict__
        assert "jump_to_scene" in provider.__dict__
        assert "check_availability" in provider.__dict__
    _CLOUD_PROVIDERS = (ArtlistProvider, ElevenLabsStudioProvider)
    for provider in _CLOUD_PROVIDERS:
        assert "check_availability" in provider.__dict__
        assert "_build_body" in provider.__dict__
        assert "_auth_headers" in provider.__dict__


def test_distinct_log_tags() -> None:
    tags = {p.LOG_TAG for p in _ENGINE_PROVIDERS}
    assert tags == {"[VEO]", "[LTX]", "[LTX-Desktop]", "[Artlist]", "[ElevenLabs-Studio]"}


def test_dubbing_is_shared_so_ltx_dubs_too() -> None:
    # The user wants LTX dubbed like Veo: the Demucs->STS->remix chain lives in the
    # base and is inherited (not a no-op) by every provider.
    src = inspect.getsource(BaseVideoProvider._apply_dubbing)
    assert "AudioSeparator" in src and "convert_voice" in src
    assert LtxProvider._apply_dubbing is BaseVideoProvider._apply_dubbing
