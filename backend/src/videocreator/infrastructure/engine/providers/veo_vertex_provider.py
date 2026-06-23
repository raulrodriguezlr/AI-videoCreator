"""
VeoProvider — Google Veo 3.1 video generation via Gemini API.

This is the PRODUCTION provider. It generates video with native synchronized audio
using Google's Veo 3.1 model. Replicates Google Flow's Scene Builder approach:
- generate_scene: Text-to-video or image-to-video
- extend_scene: Extend a previous clip (+7s, up to 20 times)
- jump_to_scene: Extract last frame → use as seed for next scene
- Reference images for character consistency

Requires: GOOGLE_API_KEY in .env, google-genai SDK, Google AI Pro/Ultra plan.
"""

import os
import re
import json
import time
import tempfile
import base64
import subprocess
import cv2
from typing import Optional, List, Dict, Any
from PIL import Image as PILImage
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials

import structlog
from videocreator.infrastructure.engine.providers.base_provider import BaseVideoProvider, VideoClip
from videocreator.infrastructure.engine.providers.elevenlabs_provider import ElevenLabsProvider
from videocreator.shared.config import get_settings

log = structlog.get_logger(__name__)
from videocreator.infrastructure.engine.utils.audio_mixer import AudioMixer
from videocreator.infrastructure.engine.utils.audio_separator import AudioSeparator
from videocreator.infrastructure.engine.utils.scene_context import SceneContextManager
from videocreator.infrastructure.engine.utils.config_loader import load_json
from videocreator.infrastructure.engine.utils.progress_manager import is_rate_limit_error, is_content_error
from videocreator.infrastructure.engine.variables import (
    VEO_MODEL,
    VEO_RESOLUTION,
    VEO_ASPECT_RATIO,
    VEO_DURATION_SECONDS,
    VEO_POLLING_INTERVAL,
    VEO_TIMEOUT,
    USE_REFERENCE_IMAGES,
    IMAGEN_MODEL,
)

class VeoVertexProvider(BaseVideoProvider):
    """Video generation using Google Veo 3.1 API through Vertex AI."""

    LOG_TAG = "[VEO_VERTEX]"

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = load_json(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

        settings = get_settings()
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        
        # Resolve the key path relative to project root
        key_path = str(settings.project_root / settings.vertex_key_path) if settings.vertex_key_path else "vertex-key.json"
        
        if os.path.exists(key_path):
            credentials = Credentials.from_service_account_file(
                key_path,
                scopes=scopes
            )
            self.client = genai.Client(
                enterprise=True,
                project=settings.vertex_project_id,
                location="us-central1",
                credentials=credentials
            )
        else:
            log.warning("veo_vertex.key_not_found", path=key_path)
            self.client = None

        # ElevenLabs TTS provider — instantiated once, reused across all scenes
        self.eleven_prov = ElevenLabsProvider(pod_config_path)

    def check_availability(self) -> bool:
        """Verify Veo API is accessible."""
        try:
            # Client is already initialized in __init__ via ApiKeyManager
            if self.client:
                log.info("veo.client_ready")
                return True
            return False
        except Exception as e:
            log.error("veo.connection_error", error=str(e))
            return False

    # ==========================================
    # SHARED CONFIG BUILDERS (DRY)
    # ==========================================

    def _build_config(self, mode: str = "text", duration: int | None = None) -> Any:
        """
        Build GenerateVideosConfig shared by all generation methods.

        Args:
            mode: 'text' (text-to-video), 'image' (image-to-video), 'extend'
            duration: requested clip length in seconds (Veo accepts 4/6/8). Gated:
                if the SDK/model rejects the field we drop it and warn once.
        """
        config_params = {
            "aspect_ratio": VEO_ASPECT_RATIO,
            "resolution": VEO_RESOLUTION,
            "number_of_videos": 1,
        }

        # NOTE: person_generation is NOT included because Veo 3.1 API
        # currently rejects all values (allow_all, allow_adult, dont_allow).
        # The API defaults to allowing people when the parameter is omitted.

        if not duration:
            return types.GenerateVideosConfig(**config_params)
        config_params["duration_seconds"] = int(duration)
        try:
            return types.GenerateVideosConfig(**config_params)
        except Exception:  # noqa: BLE001 — degrade gracefully if field unsupported
            config_params.pop("duration_seconds", None)
            if not getattr(self, "_warned_no_duration", False):
                log.warning("veo.duration_param_unsupported", model=getattr(self, "model", "veo-vertex"))
                self._warned_no_duration = True
            return types.GenerateVideosConfig(**config_params)

    def clamp_duration(self, seconds: float, mode: str = "text") -> int:
        """Veo accepts only discrete clip lengths — snap to nearest (ties → longer).

        For image-to-video (reference_to_video), only [8] is supported.
        """
        if mode == "image":
            return 8
        return min((4, 6, 8), key=lambda v: (abs(v - seconds), -v))

    def _build_gen_params(
        self,
        prompt: str,
        mode: str = "text",
        image=None,
        video=None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
        narrative_phase: str = "",
        duration: Optional[int] = None,
    ) -> dict:
        """
        Build the full parameter dict for client.models.generate_videos().
        Single source of truth for all generation calls.
        """
        config = self._build_config(mode=mode, duration=duration)
        
        # Vertex AI only serves GA `-001` ids — explicit setting, never derived
        # from the Gemini-API id by string surgery (the two catalogs differ).
        # The per-episode selection (set by the render handler in
        # `variables.VERTEX_VEO_MODEL`) wins; otherwise the config default.
        from videocreator.shared.config import get_settings
        from videocreator.infrastructure.engine import variables as _vars
        vertex_model = getattr(_vars, "VERTEX_VEO_MODEL", None) or get_settings().vertex_veo_model

        # Base parameters
        gen_params = {
            "model": vertex_model,
            "prompt": prompt,
            "config": config,
        }

        if image is not None:
            gen_params["image"] = image

        if video is not None:
            gen_params["video"] = video

        # NOTE: negative_prompt is set but Veo 3.1 silently ignores it.
        # Kept for forward compatibility if future API versions support it.
        if negative_prompt:
            config.negative_prompt = negative_prompt

        # Reference images for character consistency
        if reference_images and USE_REFERENCE_IMAGES:
            ref_images = self._load_reference_images(reference_images)
            if ref_images:
                config.reference_images = ref_images
                log.info("veo.reference_images", count=len(ref_images))

        return gen_params

    # ==========================================
    # SCENE GENERATION METHODS
    # ==========================================

    def generate_scene(
        self,
        prompt: str,
        duration: int = VEO_DURATION_SECONDS,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        """
        Generate a single video clip using Veo 3.1 text-to-video.
        Uses referenceImages for character consistency if provided.
        """
        # Character reference images activate the `reference_to_video` feature,
        # which only accepts [8]s clips — clamp accordingly (mode="image").
        use_refs = bool(reference_images) and USE_REFERENCE_IMAGES
        eff_duration = self.clamp_duration(duration, mode="image" if use_refs else "text")
        log.info("veo.generate_scene", prompt=prompt[:80], model=VEO_MODEL, duration_s=eff_duration, resolution=VEO_RESOLUTION)

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="text",
            reference_images=reference_images,
            negative_prompt=negative_prompt,
            duration=eff_duration,
        )
        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(
            operation, prompt, seed,
            save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
            duration=eff_duration,
        )

    def extend_scene(
        self,
        video_clip: VideoClip,
        prompt: str,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        """
        Extend an existing Veo-generated video.
        """
        log.info("veo.extend_scene", prompt=prompt[:60])

        if not video_clip.video_ref:
            raise ValueError(
                "video_clip.video_ref es None. "
                "Solo se pueden extender vídeos generados por Veo."
            )

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="extend",
            video=video_clip.video_ref,
        )

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(
            operation, prompt, video_clip.seed,
            save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
        )

    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
        duration: int = 8,
        **kwargs,
    ) -> VideoClip:
        """
        Create a new scene using the last frame of the previous clip.
        Extracts the last frame -> passes as image input to Veo.
        This replicates Google Flow's Jump To feature.
        """
        log.info("veo.jump_to_scene", prompt=prompt[:60])

        # Extract last frame from previous video
        last_frame = self._extract_last_frame(previous_clip.file_path)

        # Fallback: try saved PNG frame if video extraction failed
        if last_frame is None and save_dir and scene_index is not None and scene_index > 0:
            frames_dir = os.path.join(os.path.dirname(save_dir), "frames")
            saved_frame_path = os.path.join(frames_dir, f"last_frame_{scene_index:02d}.png")
            if os.path.exists(saved_frame_path):
                log.info("veo.using_saved_frame", frame=os.path.basename(saved_frame_path))
                image_bytes = open(saved_frame_path, "rb").read()
                last_frame = types.Image(image_bytes=image_bytes, mime_type="image/png")

        if last_frame is None:
            log.warning("veo.no_last_frame_generating_fresh")
            return self.generate_scene(
                prompt, reference_images=reference_images,
                save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
            )

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="image",
            image=last_frame,
            duration=self.clamp_duration(duration, mode="image"),
            # NOTE: Do NOT pass reference_images here.
            # Veo 3.1 rejects image + reference_images simultaneously.
            # The last frame already provides visual continuity.
        )

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(
            operation, prompt,
            save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
        )

    def _handle_scene_error(
        self, error: Exception, *, i: int, scene: dict, scene_num: int,
        clips: List[VideoClip], transition: str, prompt: str,
        scene_duration: int, ref_images: List[str], negative: Optional[str],
        narrative_phase: str, clips_dir: str, scene_num_str: str,
        progress_manager=None, incoming_transition: str = "cut",
        is_resume_bridge: bool = False,
    ) -> dict:
        """
        Handle a scene generation error.
        Vertex AI using Service Account does not rotate keys.
        """
        error_msg = str(error)
        log.error("veo_vertex.scene_error", scene=scene_num, error=error_msg[:120])

        if is_rate_limit_error(error):
            log.error("veo_vertex.rate_limited")
            if progress_manager:
                progress_manager.mark_scene_failed(i, error_msg, is_rate_limit=True)
            return {"rate_limited": True}
        else:
            # Non-retriable error
            log.error("veo_vertex.non_retriable_error", scene=scene_num)
            if progress_manager:
                progress_manager.mark_scene_failed(i, error_msg)
            return {}

    def _on_clip_success(self) -> None:
        pass

    def _model_label(self) -> str:
        from videocreator.shared.config import get_settings
        return get_settings().vertex_veo_model

    # ==========================================
    # INTERNAL HELPER METHODS
    # ==========================================

    def _poll_and_download(
        self,
        operation,
        prompt: str,
        seed: Optional[int] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
        duration: Optional[int] = None,
    ) -> VideoClip:
        """Poll operation status and download the generated video."""
        elapsed = 0
        while not operation.done:
            if elapsed >= VEO_TIMEOUT:
                raise TimeoutError(f"Operación excedió timeout de {VEO_TIMEOUT}s")
            log.info("veo.polling", elapsed_s=elapsed)
            time.sleep(VEO_POLLING_INTERVAL)
            elapsed += VEO_POLLING_INTERVAL
            operation = self.client.operations.get(operation=operation)

        # Check for backend errors
        if hasattr(operation, "error") and operation.error:
            raise RuntimeError(f"Backend API Error: {operation.error}")

        if not hasattr(operation, "response") or not operation.response:
            raise RuntimeError("Backend returned an empty response with no errors.")

        # Download the generated video. An empty list here usually means the
        # RAI safety filter dropped the output — surface the reason instead of
        # the opaque legacy message.
        if not hasattr(operation.response, "generated_videos") or not operation.response.generated_videos:
            filtered = getattr(operation.response, "rai_media_filtered_count", 0)
            reasons = getattr(operation.response, "rai_media_filtered_reasons", None)
            if filtered:
                raise RuntimeError(
                    f"Veo filtró el video por políticas de contenido "
                    f"({filtered} filtrados): {reasons or 'sin detalle'}. "
                    f"Reformula el prompt de la escena."
                )
            raise RuntimeError(
                "Backend response did not contain 'generated_videos'. "
                f"Modelo: {VEO_MODEL} — si es un id '-preview' retirado, "
                f"actualiza VEO_MODEL en engine/variables.py. "
                f"Respuesta: {operation.response!r}"[:500]
            )

        generated = operation.response.generated_videos[0]
        
        # Build filename — structured if scene info provided, else legacy
        if scene_index is not None:
            filename = f"clip_{scene_index + 1:02d}.mp4"
        else:
            safe_name = prompt[:40].replace(" ", "_").replace("'", "").replace('"', "")
            filename = f"scene_{safe_name}_{int(time.time())}.mp4"

        # Save to episode clips dir or fallback to assets
        target_dir = save_dir if save_dir else self.assets_dir
        output_path = os.path.join(target_dir, filename)
        
        # Vertex AI provides the video directly as bytes
        if hasattr(generated.video, "video_bytes") and generated.video.video_bytes:
            with open(output_path, "wb") as f:
                f.write(generated.video.video_bytes)
        else:
            # Fallback to files.download if it's the Developer API
            self.client.files.download(file=generated.video)
            generated.video.save(output_path)

        log.info("veo.clip_downloaded", path=output_path)

        return VideoClip(
            file_path=output_path,
            duration=duration or VEO_DURATION_SECONDS,
            seed=seed,
            video_ref=generated.video,
        )

    def _extract_last_frame(self, video_path: str) -> Optional[Any]:
        """Extract the last frame from a video file using OpenCV.
        Returns a google.genai types.Image with base64 encoded data."""
        try:

            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if total_frames <= 0:
                cap.release()
                return None

            # Seek to last frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
            ret, frame = cap.read()
            cap.release()

            if not ret:
                return None

            # Encode frame as PNG bytes
            success, buffer = cv2.imencode(".png", frame)
            if not success:
                return None

            # Convert to types.Image (base64 + mimeType)
            image_bytes = buffer.tobytes()
            return types.Image(
                image_bytes=image_bytes,
                mime_type="image/png",
            )

        except ImportError:
            log.warning("veo.opencv_not_installed")
            return None
        except Exception as e:
            log.warning("veo.frame_extraction_error", error=str(e))
            return None

    def _save_last_frame(self, video_path: str, clips_dir: str, scene_index: int):
        """Save the last frame of a clip as PNG for resume safety."""
        frames_dir = os.path.join(os.path.dirname(clips_dir), "frames")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame_path = os.path.join(frames_dir, f"last_frame_{scene_index + 1:02d}.png")
                cv2.imwrite(frame_path, frame)
                log.info("veo.last_frame_saved", frame=os.path.basename(frame_path))
        except Exception as e:
            log.warning("veo.last_frame_save_failed", error=str(e))

    def _load_reference_images(self, image_paths: List[str]) -> list:
        """Load reference images for character consistency."""
        ref_images = []
        for path in image_paths[:3]:  # Max 3 reference images
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        image_bytes = f.read()
                        
                    ext = os.path.splitext(path)[1].lower()
                    mime_type = "image/png" if ext == ".png" else "image/jpeg"
                    
                    ref_images.append(
                        types.VideoGenerationReferenceImage(
                            image=types.Image(
                                image_bytes=image_bytes,
                                mime_type=mime_type,
                            ),
                            reference_type="asset",
                        )
                    )
                except Exception as e:
                    log.warning("veo.ref_image_load_failed", path=path, error=str(e))
        return ref_images

    def _generate_anchor_image(self, episode_dir: str, script: dict, scenes: list) -> Optional[str]:
        """
        Phase 4: Generate an episode-specific reference image (Anchor Image) using Imagen 3.
        This provides Veo with a character reference that already matches the episode's
        environment and lighting, maximizing consistency.
        """
        anchor_path = os.path.join(episode_dir, "anchor_image.png")
        if os.path.exists(anchor_path):
            log.info("veo.anchor_image_exists", path=anchor_path)
            return anchor_path

        log.info("veo.anchor_image_generating")
        
        # Build prompt from config and script
        art_style = self.config.get("consistency", {}).get("art_style", "3D style")
        char_desc = ""
        for char in self.config.get("characters", []):
            if char.get("role") == "protagonist":
                char_desc = char.get("visual_description", "")
                break
                
        # Extract environment from first scene
        first_scene = scenes[0].get("visual_prompt", "") if scenes else ""
        
        prompt = f"{art_style}. Character: {char_desc}. Environment: {first_scene}. Ensure the character is clearly visible, full body or medium shot, well-lit."
        
        try:
            result = self.client.models.generate_images(
                model=IMAGEN_MODEL,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="16:9"
                )
            )
            
            if result.generated_images:
                img_bytes = result.generated_images[0].image.image_bytes
                with open(anchor_path, "wb") as f:
                    f.write(img_bytes)
                log.info("veo.anchor_image_saved", path=anchor_path)
                return anchor_path

        except Exception as e:
            log.warning("veo.anchor_image_error", error=str(e))
            
        return None

    def _get_character_reference_images(self) -> List[str]:
        """Get reference image paths from pod config characters.

        Each character may have several reference images (`reference_images`);
        `reference_image` (singular) is still honoured for older configs. Paths
        resolve relative to the pod directory.
        """
        ref_images = []
        for char in self.config.get("characters", []):
            paths = list(char.get("reference_images") or [])
            single = char.get("reference_image")
            if single and single not in paths:
                paths.append(single)
            for ref_path in paths:
                full_path = os.path.join(self.pod_dir, ref_path)
                if os.path.exists(full_path) and full_path not in ref_images:
                    ref_images.append(full_path)
        return ref_images


