"""
LtxDesktopProvider — LTX video generation via the LTX-Desktop app.

LTX-Desktop (github.com/Lightricks/LTX-Desktop) runs a local FastAPI backend
that renders on the GPU (or LTX cloud) and writes the result to disk. This
provider drives it through the SAME scene-builder pipeline as every other
provider: it reuses LtxProvider's proven generate_full_video loop, last-frame
extraction and concat, and only swaps the per-clip generation primitives from
ComfyUI workflows to LTX-Desktop's HTTP API.

Text-to-video by default; image-to-video (jump-to-scene) seeds from the previous
clip's last frame via the request's `imagePath`.

Endpoints used (base = LTX_DESKTOP_URL):
- GET  /health
- POST /api/generate  {prompt, model, duration, resolution, fps, audio,
                       negativePrompt, aspectRatio, imagePath?} -> {status, video_path}
"""

import os
import shutil
import time
from typing import List, Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

from videocreator.infrastructure.engine.providers.base_provider import (
    BaseVideoProvider,
    VideoClip,
)
from videocreator.infrastructure.engine.providers.ltx_provider import LtxProvider
from videocreator.infrastructure.engine.variables import (
    LTX_DESKTOP_ASPECT_RATIO,
    LTX_DESKTOP_FPS,
    LTX_DESKTOP_MODEL,
    LTX_DESKTOP_RESOLUTION,
    LTX_DESKTOP_TIMEOUT,
    LTX_DESKTOP_URL,
)


# LTX-Desktop only accepts these specific duration values (seconds).
_LTX_VALID_DURATIONS = (5, 6, 8, 10, 12, 14, 16, 18, 20)


def _clamp_duration(raw: int) -> int:
    """Snap a requested duration to the nearest LTX-Desktop-accepted value."""
    return min(_LTX_VALID_DURATIONS, key=lambda d: abs(d - raw))


class LtxDesktopProvider(LtxProvider):
    """LTX generation via the LTX-Desktop app, on the shared scene-builder loop."""

    LOG_TAG = "[LTX-Desktop]"

    def __init__(self, pod_config_path: str):
        # Bypass LtxProvider.__init__ (it resolves a ComfyUI text encoder); set up
        # the same directory layout without touching ComfyUI.
        BaseVideoProvider.__init__(self, pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        # Read the chosen pipeline live — the handler sets engine_vars.LTX_DESKTOP_MODEL
        # right before constructing us; a value-import would freeze the default.
        from videocreator.infrastructure.engine import variables as engine_vars
        self._model = engine_vars.LTX_DESKTOP_MODEL
        # Auto-discover the running LTX-Desktop backend (port + bearer token from
        # its process env); fall back to the configured URL with no token.
        from videocreator.infrastructure.providers.ltx_desktop import discover_ltx_desktop
        found = discover_ltx_desktop()
        self.base_url, self.auth_token = found if found else (LTX_DESKTOP_URL, "")

    @property
    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}

    def _model_label(self) -> str:
        return self._model

    # ---- availability -----------------------------------------------------
    def check_availability(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5, headers=self._auth_headers)
            ok = r.status_code == 200
            if ok:
                log.info("ltx_desktop.ready", url=self.base_url, model=LTX_DESKTOP_MODEL)
            else:
                log.error("ltx_desktop.health_failed", status=r.status_code)
            return ok
        except Exception as e:  # noqa: BLE001 — availability must never raise
            log.error("ltx_desktop.unavailable", url=self.base_url, error=str(e))
            return False

    # ---- generation primitives (override ComfyUI with LTX-Desktop HTTP) ----
    def generate_scene(
        self,
        prompt: str,
        duration: int = 5,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        # LTX-Desktop API treats `imagePath` strictly as Frame 0 (Image-to-Video).
        # We cannot pass a character reference sheet (character on black background) 
        # as Frame 0, otherwise the video starts in a black void.
        # So for fresh scenes, we do pure Text-to-Video.
        mode = "T2V"
        log.info("ltx_desktop.generate_scene", mode=mode, prompt=prompt[:60])
        src = self._submit(prompt, duration, negative_prompt, image_path=None)
        out = self._place_clip(src, save_dir, scene_index)
        return VideoClip(file_path=out, duration=duration, seed=seed)

    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        """Image-to-video: seed the new scene from the previous clip's last frame."""
        log.info("ltx_desktop.jump_to_scene", prompt=prompt[:60])
        last_frame = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)
        if not last_frame:
            log.warning("ltx_desktop.no_last_frame_generating_t2v")
            return self.generate_scene(
                prompt=prompt, save_dir=save_dir, scene_index=scene_index,
                narrative_phase=narrative_phase,
            )
        src = self._submit(prompt, 8, None, image_path=last_frame)
        out = self._place_clip(src, save_dir, scene_index)
        return VideoClip(file_path=out, duration=8, seed=None)

    # ---- LTX-Desktop HTTP --------------------------------------------------
    def _submit(
        self, prompt: str, duration: int, negative_prompt: Optional[str], image_path: Optional[str],
    ) -> str:
        """POST /api/generate and return the local video_path the app wrote."""
        body = {
            "prompt": prompt,
            "model": self._model,
            "duration": _clamp_duration(max(1, int(round(duration)))),
            "resolution": LTX_DESKTOP_RESOLUTION,
            "fps": LTX_DESKTOP_FPS,
            "audio": True,
            "negativePrompt": negative_prompt or "",
            "aspectRatio": LTX_DESKTOP_ASPECT_RATIO,
            "cameraMotion": "none",
        }
        if image_path:
            body["imagePath"] = image_path
        resp = httpx.post(
            f"{self.base_url}/api/generate", json=body, timeout=LTX_DESKTOP_TIMEOUT,
            headers=self._auth_headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"[LTX-Desktop] HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "complete":
            raise RuntimeError(f"[LTX-Desktop] generación {data.get('status', 'fallida')}")
        video_path = data.get("video_path")
        if not video_path:
            raise RuntimeError("[LTX-Desktop] completado pero sin video_path")
        return str(video_path)

    def _place_clip(
        self, src_path: str, save_dir: Optional[str], scene_index: Optional[int],
    ) -> str:
        """Copy the app's output into the episode's clips dir with the standard name."""
        target_dir = save_dir or self.assets_dir
        os.makedirs(target_dir, exist_ok=True)
        if scene_index is not None:
            name = f"clip_{scene_index + 1:02d}.mp4"
        else:
            name = f"ltx_{int(time.time())}.mp4"
        out = os.path.join(target_dir, name)
        shutil.copyfile(src_path, out)
        log.info("ltx_desktop.clip_placed", path=out)
        return out
