"""HTTP cloud video providers on the shared Scene Builder (Artlist, ElevenLabs).

These run inside the same sync engine pipeline as Veo/LTX-Desktop — they only
implement the atomic model calls (generate_scene / jump_to_scene), so they
inherit the identical dispatch, dubbing, concat and reference handling. Each
submits a generation job over HTTP, polls until done, downloads the result and
writes it to ``clips/clip_NN.mp4`` where the pipeline expects it.

Vendor request/response shaping mirrors the async discovery adapters
(``infrastructure/providers/{artlist,elevenlabs_studio}_provider.py``); those
stay only for live model-catalog discovery in the REST layer.
"""

import os
import time
from typing import Any, List, Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

from videocreator.infrastructure.engine.providers.base_provider import (
    BaseVideoProvider,
    VideoClip,
)

_POLL_INTERVAL_S = 3.0
_POLL_TIMEOUT_S = 600.0
_REQUEST_TIMEOUT_S = 60.0


class _HttpCloudVideoProvider(BaseVideoProvider):
    """Shared sync submit→poll→download→place-on-disk for cloud video APIs."""

    base_url: str = ""

    def __init__(self, pod_config_path: str):
        BaseVideoProvider.__init__(self, pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)

    def _load_config(self, path: str) -> dict:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ---- per-vendor hooks (implemented by subclasses) ---------------------
    def _auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _build_body(
        self, prompt: str, duration: int, negative: Optional[str],
        reference_images: Optional[List[str]], image_seed: Optional[str],
    ) -> dict[str, Any]:
        raise NotImplementedError

    _submit_path: str = ""

    def _status_path(self, job_id: str) -> str:
        raise NotImplementedError

    def _job_id(self, submit_payload: dict[str, Any]) -> str:
        return str(submit_payload.get("id") or submit_payload.get("job_id") or "")

    @staticmethod
    def _is_done(p: dict[str, Any]) -> bool:
        return p.get("status") in {"succeeded", "completed"}

    @staticmethod
    def _is_failed(p: dict[str, Any]) -> bool:
        return p.get("status") in {"failed", "error", "cancelled"}

    @staticmethod
    def _output_url(p: dict[str, Any]) -> str:
        return str(p.get("output_url") or p.get("video_url") or "")

    # ---- shared transport -------------------------------------------------
    def _run_job(
        self, prompt: str, duration: int, negative: Optional[str],
        reference_images: Optional[List[str]], image_seed: Optional[str],
        save_dir: Optional[str], scene_index: Optional[int],
    ) -> str:
        body = self._build_body(prompt, duration, negative, reference_images, image_seed)
        headers = self._auth_headers()
        with httpx.Client(base_url=self.base_url, timeout=_REQUEST_TIMEOUT_S, headers=headers) as c:
            r = c.post(self._submit_path, json=body)
            r.raise_for_status()
            job_id = self._job_id(r.json())
            if not job_id:
                raise RuntimeError(f"{self.LOG_TAG} no job id returned")
            log.info("http_cloud.job_submitted", provider=self.LOG_TAG, job_id=job_id)
            elapsed = 0.0
            while elapsed < _POLL_TIMEOUT_S:
                s = c.get(self._status_path(job_id))
                s.raise_for_status()
                payload = s.json()
                if self._is_failed(payload):
                    raise RuntimeError(f"{self.LOG_TAG} job failed: {payload.get('error') or payload}")
                if self._is_done(payload):
                    url = self._output_url(payload)
                    if not url:
                        raise RuntimeError(f"{self.LOG_TAG} job done but no output url")
                    return self._download(url, save_dir, scene_index)
                time.sleep(_POLL_INTERVAL_S)
                elapsed += _POLL_INTERVAL_S
            raise TimeoutError(f"{self.LOG_TAG} job {job_id} timed out after {_POLL_TIMEOUT_S:.0f}s")

    def _download(self, url: str, save_dir: Optional[str], scene_index: Optional[int]) -> str:
        with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as c:
            resp = c.get(url)
            resp.raise_for_status()
            data = resp.content
        target_dir = save_dir or self.assets_dir
        os.makedirs(target_dir, exist_ok=True)
        name = f"clip_{scene_index + 1:02d}.mp4" if scene_index is not None else f"clip_{int(time.time())}.mp4"
        out = os.path.join(target_dir, name)
        with open(out, "wb") as f:
            f.write(data)
        log.info("http_cloud.clip_downloaded", provider=self.LOG_TAG, path=out)
        return out

    # ---- atomic ops (the only thing the pipeline calls per scene) ---------
    def generate_scene(
        self, prompt: str, duration: int = 8, seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None, negative_prompt: Optional[str] = None,
        save_dir: Optional[str] = None, scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        out = self._run_job(prompt, duration, negative_prompt, reference_images, None, save_dir, scene_index)
        return VideoClip(file_path=out, duration=duration, seed=seed)

    def jump_to_scene(
        self, previous_clip: VideoClip, prompt: str,
        reference_images: Optional[List[str]] = None, save_dir: Optional[str] = None,
        scene_index: Optional[int] = None, narrative_phase: str = "",
    ) -> VideoClip:
        # Seed image-to-video from the previous clip's last frame.
        last_frame = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)
        out = self._run_job(prompt, 8, None, reference_images, last_frame, save_dir, scene_index)
        return VideoClip(file_path=out, duration=8, seed=None)

    def extend_scene(self, video_clip: VideoClip, prompt: str, **kwargs: Any) -> VideoClip:
        return self.jump_to_scene(previous_clip=video_clip, prompt=prompt, **kwargs)


class ArtlistProvider(_HttpCloudVideoProvider):
    """Artlist multi-model hub on the shared pipeline (ARTLIST_API_TOKEN)."""

    LOG_TAG = "[Artlist]"

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.base_url = os.environ.get("ARTLIST_BASE_URL", "https://api.artlist.io")
        from videocreator.infrastructure.engine import variables as engine_vars
        self._model = getattr(engine_vars, "ARTLIST_MODEL", "kling-3.0")

    def _model_label(self) -> str:
        return self._model

    def check_availability(self) -> bool:
        if not os.environ.get("ARTLIST_API_TOKEN"):
            log.warning("artlist.api_token_missing")
            return False
        return True

    def _auth_headers(self) -> dict[str, str]:
        token = os.environ.get("ARTLIST_API_TOKEN", "")
        return {"Authorization": f"Bearer {token}", "accept": "application/json"}

    _submit_path = "/v1/generations"

    def _status_path(self, job_id: str) -> str:
        return f"/v1/generations/{job_id}"

    def _build_body(self, prompt, duration, negative, reference_images, image_seed):
        body: dict[str, Any] = {"model": self._model, "prompt": prompt, "duration_seconds": duration}
        if negative:
            body["negative_prompt"] = negative
        # Kling uses reference_image_keys as literal first frames (Image-to-Video), causing morphing when used for character consistency.
        # Veo correctly uses them as character reference styles.
        if reference_images and "kling" not in self._model.lower():
            body["reference_image_keys"] = list(reference_images)
        if image_seed:
            body["seed_image"] = image_seed
        return body


class ElevenLabsStudioProvider(_HttpCloudVideoProvider):
    """ElevenLabs Studio 3.0 on the shared pipeline (ELEVENLABS_API_KEY)."""

    LOG_TAG = "[ElevenLabs-Studio]"

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.base_url = "https://api.elevenlabs.io"
        self._model = os.environ.get("ELEVENLABS_STUDIO_MODEL_ID", "studio-3.0")

    def _model_label(self) -> str:
        return self._model

    def check_availability(self) -> bool:
        if not os.environ.get("ELEVENLABS_API_KEY"):
            log.warning("elevenlabs_studio.api_key_missing")
            return False
        return True

    def _auth_headers(self) -> dict[str, str]:
        return {"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", ""), "accept": "application/json"}

    _submit_path = "/v1/studio/jobs"

    def _status_path(self, job_id: str) -> str:
        return f"/v1/studio/jobs/{job_id}"

    def _job_id(self, submit_payload):
        return str(submit_payload.get("job_id") or "")

    @staticmethod
    def _is_done(p):
        return p.get("status") == "completed"

    @staticmethod
    def _is_failed(p):
        return p.get("status") in {"failed", "error"}

    def _build_body(self, prompt, duration, negative, reference_images, image_seed):
        body: dict[str, Any] = {"model_id": self._model, "prompt": prompt, "duration_seconds": duration}
        if negative:
            body["negative_prompt"] = negative
        if reference_images:
            body["reference_image_keys"] = list(reference_images)
        if image_seed:
            body["seed_image"] = image_seed
        return body
