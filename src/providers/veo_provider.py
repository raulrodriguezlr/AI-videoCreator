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

from src.providers.base_provider import BaseVideoProvider, VideoClip
from src.variables import (
    VEO_MODEL,
    VEO_RESOLUTION,
    VEO_ASPECT_RATIO,
    VEO_DURATION_SECONDS,
    VEO_POLLING_INTERVAL,
    VEO_TIMEOUT,
    USE_REFERENCE_IMAGES,
)
from src.utils.progress_manager import is_rate_limit_error, is_content_error

class VeoProvider(BaseVideoProvider):
    """Video generation using Google Veo 3.1 API."""

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

        # Initialize Google GenAI client
        self.client = self._init_client()

    def _load_config(self, path: str) -> dict:
        """Load pod configuration from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _init_client(self):
        """Initialize the Google GenAI client."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY no encontrada en .env. "
                "Necesitas una API key de Google AI Studio: https://aistudio.google.com/apikey"
            )
        return genai.Client(api_key=api_key)

    def check_availability(self) -> bool:
        """Verify Veo API is accessible."""
        try:
            # Try a simple API call to verify connectivity
            self._init_client()
            print("[VEO] ✅ Google GenAI client inicializado correctamente")
            return True
        except Exception as e:
            print(f"[VEO] ❌ Error de conexión: {e}")
            return False

    # ==========================================
    # SHARED CONFIG BUILDERS (DRY)
    # ==========================================

    def _build_config(self, mode: str = "text") -> Any:
        """
        Build GenerateVideosConfig shared by all generation methods.

        Args:
            mode: 'text' (text-to-video), 'image' (image-to-video), 'extend'
        """
        config_params = {
            "aspect_ratio": VEO_ASPECT_RATIO,
            "resolution": VEO_RESOLUTION,
            "number_of_videos": 1,
        }

        # NOTE: person_generation is NOT included because Veo 3.1 API
        # currently rejects all values (allow_all, allow_adult, dont_allow).
        # The API defaults to allowing people when the parameter is omitted.

        return types.GenerateVideosConfig(**config_params)

    def _build_gen_params(
        self,
        prompt: str,
        mode: str = "text",
        image=None,
        video=None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
    ) -> dict:
        """
        Build the full parameter dict for client.models.generate_videos().
        Single source of truth for all generation calls.
        """
        config = self._build_config(mode=mode)

        gen_params = {
            "model": VEO_MODEL,
            "prompt": prompt,
            "config": config,
        }

        if image is not None:
            gen_params["image"] = image

        if video is not None:
            gen_params["video"] = video

        if negative_prompt:
            config.negative_prompt = negative_prompt

        # Reference images for character consistency
        if reference_images and USE_REFERENCE_IMAGES:
            ref_images = self._load_reference_images(reference_images)
            if ref_images:
                config.reference_images = ref_images
                print(f"[VEO]    📸 {len(ref_images)} reference images para consistency")

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
    ) -> VideoClip:
        """
        Generate a single video clip using Veo 3.1 text-to-video.
        Uses referenceImages for character consistency if provided.
        """
        print(f"[VEO] 🎬 Generando escena: '{prompt[:80]}...'")
        print(f"[VEO]    Modelo: {VEO_MODEL} | Duración: {duration}s | Resolución: {VEO_RESOLUTION}")

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="text",
            reference_images=reference_images,
            negative_prompt=negative_prompt,
        )

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(operation, prompt, seed)

    def extend_scene(
        self,
        video_clip: VideoClip,
        prompt: str,
    ) -> VideoClip:
        """
        Extend an existing Veo-generated video by ~7 seconds.
        Can be called up to 20 times for max ~148s total.
        """
        print(f"[VEO] 🔄 Extendiendo escena: '{prompt[:60]}...'")

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
        return self._poll_and_download(operation, prompt, video_clip.seed)

    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
    ) -> VideoClip:
        """
        Create a new scene using the last frame of the previous clip.
        Extracts the last frame → passes as image input to Veo.
        This replicates Google Flow's "Jump To" feature.
        """
        print(f"[VEO] ⏭️  Jump To nueva escena: '{prompt[:60]}...'")

        # Extract last frame from previous video
        last_frame = self._extract_last_frame(previous_clip.file_path)

        if last_frame is None:
            print("[VEO] ⚠️  No se pudo extraer último frame. Generando sin seed visual.")
            return self.generate_scene(prompt, reference_images=reference_images)

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="image",  # image-to-video: NO person_generation
            image=last_frame,
            reference_images=reference_images,
        )

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(operation, prompt)

    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
        resume_from: int = 0,
        progress_manager=None,
    ) -> str:
        """
        Orchestrate full video generation using Scene Builder logic.

        RESILIENT: each scene is wrapped in try/except. If a scene fails:
        - Rate limit (429) → save progress, stop cleanly, can resume later
        - Content error → skip scene, continue with next
        - Other error → save progress, try next scene

        Args:
            script: Full script dict with scenes
            output_path: Path for final concatenated video
            resume_from: Scene index to resume from (0 = start fresh)
            progress_manager: Optional ProgressManager for persistence
        """
        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("El script no tiene escenas.")

        title = script.get("title", "Untitled")
        print(f"\n{'='*60}")
        print(f"[VEO] 🎬 Scene Builder — '{title}'")
        print(f"[VEO]    {len(scenes)} escenas a generar")
        if resume_from > 0:
            print(f"[VEO]    ▶️  Continuando desde escena {resume_from + 1}")
        print(f"{'='*60}\n")

        # Load character reference images from config
        ref_images = self._get_character_reference_images()
        # Collect clips — load previously generated clips if resuming
        clips: List[VideoClip] = []
        if resume_from > 0 and progress_manager:
            completed = progress_manager.get_completed_clips()
            for c in completed:
                if c.get("clip_path") and os.path.exists(c["clip_path"]):
                    clips.append(VideoClip(
                        file_path=c["clip_path"],
                        duration=c.get("duration_seconds", VEO_DURATION_SECONDS),
                    ))
            print(f"[VEO]    📂 {len(clips)} clips previos recuperados")

        rate_limited = False

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)

            # Skip already completed scenes
            if i < resume_from:
                continue

            prompt = self._build_cinematographic_prompt(scene)
            negative = scene.get("negative_prompt")
            transition = scene.get("transition_to_next", "jump")

            print(f"\n--- Escena {scene_num}/{len(scenes)} ---")

            try:
                if i == 0 or not clips:
                    # First scene or no previous clips: pure text-to-video
                    clip = self.generate_scene(
                        prompt=prompt,
                        seed=scene.get("seed"),
                        reference_images=ref_images,
                        negative_prompt=negative,
                    )
                elif transition == "extend" and clips:
                    # Continue same scene
                    clip = self.extend_scene(
                        video_clip=clips[-1],
                        prompt=prompt,
                    )
                else:
                    # Jump to new scene (default)
                    clip = self.jump_to_scene(
                        previous_clip=clips[-1],
                        prompt=prompt,
                        reference_images=ref_images,
                    )

                clips.append(clip)
                print(f"[VEO] ✅ Escena {scene_num} generada: {clip.file_path}")

                # Persist progress
                if progress_manager:
                    progress_manager.mark_scene_completed(
                        scene_index=i,
                        clip_path=clip.file_path,
                        model_used=VEO_MODEL,
                    )

            except Exception as e:
                error_msg = str(e)
                print(f"[VEO] ❌ Error en escena {scene_num}: {error_msg[:120]}")

                if is_rate_limit_error(e):
                    print(f"[VEO] 🛑 Rate limit alcanzado. Guardando progreso...")
                    if progress_manager:
                        progress_manager.mark_scene_failed(i, error_msg, is_rate_limit=True)
                    rate_limited = True
                    break  # Stop — no point trying more scenes
                elif is_content_error(e):
                    print(f"[VEO] ⚠️  Error de contenido. Saltando escena {scene_num}...")
                    if progress_manager:
                        progress_manager.mark_scene_skipped(i, error_msg)
                    continue
                else:
                    print(f"[VEO] ⚠️  Error inesperado. Intentando siguiente escena...")
                    if progress_manager:
                        progress_manager.mark_scene_failed(i, error_msg)
                    continue

        # Final result
        if not clips:
            error_msg = "No se generó ningún clip."
            if progress_manager:
                progress_manager.mark_episode_failed(error_msg)
            raise RuntimeError(error_msg)

        # Concatenate clips
        if len(clips) == 1:
            final_path = clips[0].file_path
        else:
            final_path = self._concatenate_clips(clips, output_path)

        # Update progress
        if progress_manager:
            if rate_limited:
                print(f"\n[VEO] ⏸️  Episodio pausado por rate limit. Resume con --resume")
                print(progress_manager.get_status_summary())
            else:
                progress_manager.mark_episode_completed(final_path)

        completed_count = len(clips)
        total_count = len(scenes)
        status = "PARCIAL" if completed_count < total_count else "COMPLETO"

        print(f"\n{'='*60}")
        print(f"[VEO] {'⏸️' if rate_limited else '✅'} Vídeo {status}: {final_path}")
        print(f"[VEO]    Clips generados: {completed_count}/{total_count}")
        print(f"{'='*60}\n")

        return final_path

    # ==========================================
    # INTERNAL HELPER METHODS
    # ==========================================

    def _poll_and_download(
        self,
        operation,
        prompt: str,
        seed: Optional[int] = None,
    ) -> VideoClip:
        """Poll operation status and download the generated video."""
        elapsed = 0
        while not operation.done:
            if elapsed >= VEO_TIMEOUT:
                raise TimeoutError(
                    f"[VEO] Timeout ({VEO_TIMEOUT}s) esperando generación de vídeo."
                )
            print(f"[VEO] ⏳ Esperando... ({elapsed}s)")
            time.sleep(VEO_POLLING_INTERVAL)
            elapsed += VEO_POLLING_INTERVAL
            operation = self.client.operations.get(operation)

        # Download the generated video
        generated = operation.response.generated_videos[0]
        self.client.files.download(file=generated.video)

        # Save to assets directory
        safe_name = prompt[:40].replace(" ", "_").replace("'", "").replace('"', "")
        filename = f"scene_{safe_name}_{int(time.time())}.mp4"
        output_path = os.path.join(self.assets_dir, filename)
        generated.video.save(output_path)

        print(f"[VEO] 💾 Descargado: {output_path}")

        return VideoClip(
            file_path=output_path,
            duration=VEO_DURATION_SECONDS,
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
            print("[VEO] ⚠️  opencv-python no instalado. No se puede extraer frame.")
            return None
        except Exception as e:
            print(f"[VEO] ⚠️  Error extrayendo frame: {e}")
            return None

    def _load_reference_images(self, image_paths: List[str]) -> list:
        """Load reference images for character consistency."""
        ref_images = []
        for path in image_paths[:3]:  # Max 3 reference images
            if os.path.exists(path):
                try:
                    img = PILImage.open(path)
                    ref_images.append(
                        types.VideoGenerationReferenceImage(
                            image=img,
                            reference_type="asset",
                        )
                    )
                except Exception as e:
                    print(f"[VEO] ⚠️  No se pudo cargar ref image {path}: {e}")
        return ref_images

    def _get_character_reference_images(self) -> List[str]:
        """Get reference image paths from pod config characters."""
        ref_images = []
        for char in self.config.get("characters", []):
            ref_path = char.get("reference_image")
            if ref_path:
                # Resolve relative to pod directory
                full_path = os.path.join(self.pod_dir, ref_path)
                if os.path.exists(full_path):
                    ref_images.append(full_path)
        return ref_images

    def _build_cinematographic_prompt(self, scene: dict) -> str:
        """
        Build a detailed cinematographic prompt from scene metadata.
        Combines visual_prompt with camera, mood, and lighting info.
        """
        parts = []

        # Camera metadata
        camera = scene.get("camera", {})
        if camera:
            shot = camera.get("shot_type", "")
            movement = camera.get("movement", "")
            angle = camera.get("angle", "")
            if shot:
                parts.append(f"{shot} shot")
            if movement:
                parts.append(f"camera {movement}")
            if angle:
                parts.append(f"{angle} angle")

        # Mood and lighting
        mood = scene.get("mood", "")
        lighting = scene.get("lighting", "")
        if mood:
            parts.append(f"{mood} mood")
        if lighting:
            parts.append(f"{lighting} lighting")

        # Main visual prompt
        visual_prompt = scene.get("visual_prompt", scene.get("narration", ""))
        parts.append(visual_prompt)

        # Audio/dialogue (Veo 3.1 generates audio natively)
        audio_text = scene.get("audio_text", "")
        if audio_text:
            parts.append(f'Narration: "{audio_text}"')

        # Art style from config
        art_style = self.config.get("consistency", {}).get("art_style", "")
        if art_style:
            parts.append(art_style)

        return ". ".join(filter(None, parts))

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str) -> str:
        """
        Concatenate multiple video clips into one final video.
        Uses ffmpeg via subprocess for reliability.
        """
        try:
            # Create concat file list for ffmpeg
            concat_list_path = os.path.join(self.assets_dir, "_concat_list.txt")
            with open(concat_list_path, "w") as f:
                for clip in clips:
                    # ffmpeg requires forward slashes or escaped backslashes
                    safe_path = clip.file_path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            # Run ffmpeg concat
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"[VEO] ⚠️  ffmpeg error: {result.stderr[:200]}")
                # Fallback: return first clip
                return clips[0].file_path

            # Cleanup temp file
            os.remove(concat_list_path)
            return output_path

        except FileNotFoundError:
            print("[VEO] ⚠️  ffmpeg no encontrado. Retornando primer clip.")
            return clips[0].file_path
