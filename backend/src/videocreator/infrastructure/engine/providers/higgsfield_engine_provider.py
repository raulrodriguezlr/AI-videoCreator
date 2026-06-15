"""Higgsfield on the legacy Scene Builder — the engine↔SDK convergence bridge.

Memes/Director already reach Higgsfield through the SDK runtime; EPISODES were
stuck on the legacy engine (Veo/LTX/Artlist). This provider closes that gap: it
subclasses `BaseVideoProvider` so it plugs into the exact same per-scene render
loop, but each atomic call delegates to the SDK `providers.d/higgsfield` adapter
(the `hf` CLI, OAuth session → spends the user's PLUS subscription credits). So
an episode can render every clip with a Higgsfield model (e.g. Kling v3.0).

The engine loop is synchronous and runs in a worker thread (`asyncio.to_thread`),
so we drive the async adapter with `asyncio.run` — safe because that thread has
no running loop.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, List, Optional

import structlog

from videocreator.infrastructure.engine.providers.base_provider import (
    BaseVideoProvider,
    VideoClip,
)
from videocreator.infrastructure.engine.utils.config_loader import load_json

log = structlog.get_logger(__name__)

#: providers.d lives at backend/providers.d (this file is …/engine/providers/x.py).
_PROVIDERS_DIR = Path(__file__).resolve().parents[5] / "providers.d"
_ADAPTER_CACHE: dict[str, Any] = {}


def _higgsfield_adapter() -> Any:
    """Load (once) the SDK higgsfield adapter via the provider registry."""
    if "adapter" not in _ADAPTER_CACHE:
        from videocreator.infrastructure.providers.sdk.registry import ProviderRegistry
        reg = ProviderRegistry(_PROVIDERS_DIR)
        reg.discover()
        loaded = reg.get("higgsfield")
        if loaded is None:
            raise RuntimeError(
                "higgsfield SDK provider not found in providers.d — cannot render"
            )
        _ADAPTER_CACHE["adapter"] = loaded.adapter
    return _ADAPTER_CACHE["adapter"]


class HiggsfieldEngineProvider(BaseVideoProvider):
    """Higgsfield models on the shared Scene Builder (spends Plus credits via CLI)."""

    LOG_TAG = "[Higgsfield]"

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = load_json(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)
        from videocreator.infrastructure.engine import variables as engine_vars
        # Default to Kling v3.0 — currently unlimited on the Plus plan.
        self._model = getattr(engine_vars, "HIGGSFIELD_MODEL", None) or "kling-3.0"

    def check_availability(self) -> bool:
        from videocreator.shared.config import get_settings
        return bool(get_settings().higgsfield_cli_path)

    # ---- atomic ops the pipeline calls per scene --------------------------
    def _generate(
        self, prompt: str, duration: int, seed: Optional[int],
        ref_images: Optional[List[str]], negative: Optional[str],
        image_seed: Optional[str], save_dir: Optional[str], scene_index: Optional[int],
    ) -> str:
        from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest
        extra: dict[str, Any] = {}
        # Kling uses input_image as literal first frames (Image-to-Video), causing morphing when used for character consistency.
        # Veo correctly uses them as character reference styles.
        img = image_seed
        if not img and ref_images and "kling" not in self._model.lower():
            img = ref_images[0]
            
        if img:
            extra["input_image"] = img
        req = GenRequest(
            prompt=prompt, duration_s=float(duration), model_id=self._model,
            seed=seed, negative_prompt=negative, extra=extra,
        )
        result = asyncio.run(_higgsfield_adapter().generate(req))
        if not result.video_bytes:
            raise RuntimeError(f"{self.LOG_TAG} produced no video bytes")
        target = save_dir or self.assets_dir
        os.makedirs(target, exist_ok=True)
        name = (f"clip_{scene_index + 1:02d}.mp4" if scene_index is not None
                else f"clip_{int(time.time())}.mp4")
        out = os.path.join(target, name)
        with open(out, "wb") as f:
            f.write(result.video_bytes)
        log.info("higgsfield.clip", model=self._model, path=out, size=len(result.video_bytes))
        return out

    def generate_scene(
        self, prompt: str, duration: int = 8, seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None, negative_prompt: Optional[str] = None,
        save_dir: Optional[str] = None, scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        out = self._generate(prompt, duration, seed, reference_images,
                             negative_prompt, None, save_dir, scene_index)
        return VideoClip(file_path=out, duration=duration, seed=seed)

    def jump_to_scene(
        self, previous_clip: VideoClip, prompt: str,
        reference_images: Optional[List[str]] = None, save_dir: Optional[str] = None,
        scene_index: Optional[int] = None, narrative_phase: str = "",
    ) -> VideoClip:
        # Image-to-video: seed from the previous clip's last frame for continuity.
        last_frame = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)
        out = self._generate(prompt, 8, None, reference_images, None,
                             last_frame, save_dir, scene_index)
        return VideoClip(file_path=out, duration=8, seed=None)

    def extend_scene(self, video_clip: VideoClip, prompt: str, **kwargs: Any) -> VideoClip:
        return self.jump_to_scene(previous_clip=video_clip, prompt=prompt, **kwargs)
