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
from src.utils.api_key_manager import get_api_key_manager
from src.utils.progress_manager import is_rate_limit_error, is_content_error
from src.variables import (
    VEO_MODEL,
    VEO_RESOLUTION,
    VEO_ASPECT_RATIO,
    VEO_DURATION_SECONDS,
    VEO_POLLING_INTERVAL,
    VEO_TIMEOUT,
    USE_REFERENCE_IMAGES,
    SMART_MODEL_SELECTION,
    SCENE_TIER_MAP,
    TIER_MODEL_MAP,
)

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

        # Initialize client via ApiKeyManager
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def _load_config(self, path: str) -> dict:
        """Load pod configuration from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

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
        narrative_phase: str = "",
    ) -> dict:
        """
        Build the full parameter dict for client.models.generate_videos().
        Single source of truth for all generation calls.
        """
        config = self._build_config(mode=mode)

        # Base parameters
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
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        """
        Generate a single video clip using Veo 3.1 text-to-video.
        Uses referenceImages for character consistency if provided.
        """
        print(f"[VEO] 🎬 Generando escena: '{prompt[:80]}...'")

        # Smart model selection
        model = VEO_MODEL
        if SMART_MODEL_SELECTION and narrative_phase:
            tier = SCENE_TIER_MAP.get(narrative_phase)
            if tier:
                model = TIER_MODEL_MAP.get(tier, VEO_MODEL)
                print(f"[VEO]    🎯 Tier: {tier} ({narrative_phase}) → {model}")

        print(f"[VEO]    Modelo: {model} | Duración: {duration}s | Resolución: {VEO_RESOLUTION}")

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="text",
            reference_images=reference_images,
            negative_prompt=negative_prompt,
        )
        # Override model for smart selection
        if SMART_MODEL_SELECTION and narrative_phase:
            tier = SCENE_TIER_MAP.get(narrative_phase)
            if tier:
                selected = TIER_MODEL_MAP.get(tier, VEO_MODEL)
                gen_params["model"] = selected

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(
            operation, prompt, seed,
            save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
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
    ) -> VideoClip:
        """
        Create a new scene using the last frame of the previous clip.
        Extracts the last frame -> passes as image input to Veo.
        This replicates Google Flow's Jump To feature.
        """
        print(f"[VEO] ⏭️  Jump To nueva escena: '{prompt[:60]}...'")

        # Extract last frame from previous video
        last_frame = self._extract_last_frame(previous_clip.file_path)

        # Fallback: try saved PNG frame if video extraction failed
        if last_frame is None and save_dir and scene_index is not None and scene_index > 0:
            saved_frame_path = os.path.join(save_dir, f"last_frame_{scene_index:02d}.png")
            if os.path.exists(saved_frame_path):
                print(f"[VEO]    📷 Usando frame guardado: {os.path.basename(saved_frame_path)}")
                image_bytes = open(saved_frame_path, "rb").read()
                last_frame = types.Image(image_bytes=image_bytes, mime_type="image/png")

        if last_frame is None:
            print("[VEO] ⚠️  No se pudo extraer último frame. Generando sin seed visual.")
            return self.generate_scene(
                prompt, reference_images=reference_images,
                save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
            )

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="image",
            image=last_frame,
            # NOTE: Do NOT pass reference_images here.
            # Veo 3.1 rejects image + reference_images simultaneously.
            # The last frame already provides visual continuity.
        )

        operation = self.client.models.generate_videos(**gen_params)
        return self._poll_and_download(
            operation, prompt,
            save_dir=save_dir, scene_index=scene_index, narrative_phase=narrative_phase,
        )

    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
        episode_dir: str = None,
        resume_from: int = 0,
        progress_manager=None,
    ) -> str:
        """
        Orchestrate full video generation using Scene Builder logic.

        RESILIENT: each scene is wrapped in try/except. If a scene fails:
        - Rate limit (429) → rotate key + retry, or save progress & stop
        - Content error → skip scene, continue with next
        - Other error → save progress, try next scene

        Args:
            script: Full script dict with scenes
            output_path: Path for final concatenated video
            episode_dir: Episode directory (clips saved to episode_dir/clips/)
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

        # Determine clip save directory
        if episode_dir:
            clips_dir = os.path.join(episode_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
        else:
            clips_dir = self.assets_dir
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

            narrative_phase = scene.get("narrative_phase", "")
            prompt = self._build_cinematographic_prompt(scene, narrative_phase)
            negative = scene.get("negative_prompt")
            transition = scene.get("transition_to_next", "jump")
            scene_duration = scene.get("duration_seconds", VEO_DURATION_SECONDS)
            # Clamp to valid range (4-8)
            scene_duration = max(4, min(scene_duration, VEO_DURATION_SECONDS))

            print(f"\n--- Escena {scene_num}/{len(scenes)} ({scene_duration}s) ---")

            try:
                scene_num_str = f"{scene_num:02d}"

                if i == 0 or not clips:
                    # First scene or no previous clips: pure text-to-video
                    clip = self.generate_scene(
                        prompt=prompt,
                        duration=scene_duration,
                        seed=scene.get("seed"),
                        reference_images=ref_images,
                        negative_prompt=negative,
                        save_dir=clips_dir,
                        scene_index=i,
                        narrative_phase=narrative_phase,
                    )
                else:
                    # All subsequent scenes use jump_to for clean cuts
                    # (extend is disabled — it duplicates content)
                    clip = self.jump_to_scene(
                        previous_clip=clips[-1],
                        prompt=prompt,
                        reference_images=ref_images,
                        save_dir=clips_dir,
                        scene_index=i,
                        narrative_phase=narrative_phase,
                    )

                clips.append(clip)
                print(f"[VEO] ✅ Escena {scene_num} generada: {clip.file_path}")
                self.key_manager.record_success()

                # Save last frame for resume safety
                self._save_last_frame(clip.file_path, clips_dir, i)

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
                    if self.key_manager.rotate_key(error_msg):
                        self.client = self.key_manager.get_client()
                        print(f"[VEO] 🔄 Reintentando escena {scene_num} con {self.key_manager.get_key_label()} ({self.key_manager.get_active_key()})...")
                        try:
                            # Retry the same scene with the new key
                            if i == 0 or not clips:
                                clip = self.generate_scene(
                                    prompt=prompt, duration=scene_duration, seed=scene.get("seed"),
                                    reference_images=ref_images, negative_prompt=negative,
                                    save_dir=clips_dir, scene_index=i, narrative_phase=narrative_phase,
                                )
                            else:
                                clip = self.jump_to_scene(
                                    previous_clip=clips[-1], prompt=prompt,
                                    reference_images=ref_images,
                                    save_dir=clips_dir, scene_index=i, narrative_phase=narrative_phase,
                                )
                            clips.append(clip)
                            self.key_manager.record_success()
                            print(f"[VEO] ✅ Escena {scene_num} generada con key rotada: {clip.file_path}")
                            if progress_manager:
                                progress_manager.mark_scene_completed(
                                    scene_index=i, clip_path=clip.file_path, model_used=VEO_MODEL,
                                )
                            continue
                        except Exception as retry_e:
                            error_msg = str(retry_e)
                            print(f"[VEO] ❌ Retry también falló: {error_msg[:120]}")

                    # All keys exhausted — stop
                    print(f"[VEO] 🛑 Todas las keys agotadas. Guardando progreso...")
                    if progress_manager:
                        progress_manager.mark_scene_failed(i, error_msg, is_rate_limit=True)
                    rate_limited = True
                    break
                else:
                    # Any other error — stop immediately and save progress
                    print(f"[VEO] 🛑 Error en escena {scene_num}. Guardando progreso y parando.")
                    if progress_manager:
                        progress_manager.mark_scene_failed(i, error_msg)
                    break

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
            elif len(clips) >= len(scenes):
                # ALL scenes completed successfully
                progress_manager.mark_episode_completed(final_path)
            else:
                # Partial generation (stopped by error) — don't mark as completed
                print(f"\n[VEO] ⏸️  Episodio parcial ({len(clips)}/{len(scenes)} clips). Resume con opción 4.")
                print(progress_manager.get_status_summary())

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
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
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
            operation = self.client.operations.get(operation=operation)

        # Check for backend errors
        if hasattr(operation, "error") and operation.error:
            raise RuntimeError(f"Backend API Error: {operation.error}")

        if not hasattr(operation, "response") or not operation.response:
            raise RuntimeError("Backend returned an empty response with no errors.")

        # Download the generated video
        if not hasattr(operation.response, "generated_videos") or not operation.response.generated_videos:
            raise RuntimeError("Backend response did not contain 'generated_videos'.")

        generated = operation.response.generated_videos[0]
        self.client.files.download(file=generated.video)

        # Build filename — structured if scene info provided, else legacy
        if scene_index is not None:
            filename = f"clip_{scene_index + 1:02d}.mp4"
        else:
            safe_name = prompt[:40].replace(" ", "_").replace("'", "").replace('"', "")
            filename = f"scene_{safe_name}_{int(time.time())}.mp4"

        # Save to episode clips dir or fallback to assets
        target_dir = save_dir if save_dir else self.assets_dir
        output_path = os.path.join(target_dir, filename)
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

    def _save_last_frame(self, video_path: str, clips_dir: str, scene_index: int):
        """Save the last frame of a clip as PNG for resume safety."""
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
                frame_path = os.path.join(clips_dir, f"last_frame_{scene_index + 1:02d}.png")
                cv2.imwrite(frame_path, frame)
                print(f"[VEO]    📷 Último frame guardado: {os.path.basename(frame_path)}")
        except Exception as e:
            print(f"[VEO] ⚠️  No se pudo guardar último frame: {e}")

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

    def _build_cinematographic_prompt(self, scene: dict, narrative_phase: str = "") -> str:
        """
        Build a detailed cinematographic prompt from scene metadata.
        Combines visual_prompt with camera, mood, lighting, and audio info.
        If the assigned model does not support audio (e.g., Veo 2), audio text is stripped
        so it doesn't get incorrectly rendered as onscreen text.
        """
        parts = []

        # Determine target model to check audio support
        model = VEO_MODEL
        if SMART_MODEL_SELECTION and narrative_phase:
            tier = SCENE_TIER_MAP.get(narrative_phase)
            if tier:
                model = TIER_MODEL_MAP.get(tier, VEO_MODEL)
                
        is_audio_supported = "veo-3" in model

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

        # Audio/dialogue with voice direction
        character = scene.get("character", "")
        audio_text = scene.get("audio_text", "")
        voice_direction = scene.get("voice_direction", "")

        if audio_text and is_audio_supported:
            # All dialogue is Tico narrating in first person — consistent voice
            voice_desc = f" ({voice_direction})" if voice_direction else " (young cheerful male voice, European Spanish)"
            parts.append(f'Tico{voice_desc} says: "{audio_text}"')

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
