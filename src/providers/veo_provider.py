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

from src.providers.base_provider import BaseVideoProvider, VideoClip
from src.providers.elevenlabs_provider import ElevenLabsProvider
from src.utils.audio_mixer import AudioMixer
from src.utils.audio_separator import AudioSeparator
from src.utils.api_key_manager import get_api_key_manager
from src.utils.scene_context import SceneContextManager
from src.utils.config_loader import load_json
from src.utils.progress_manager import is_rate_limit_error, is_content_error
from src.variables import (
    VEO_MODEL,
    VEO_RESOLUTION,
    VEO_ASPECT_RATIO,
    VEO_DURATION_SECONDS,
    VEO_POLLING_INTERVAL,
    VEO_TIMEOUT,
    USE_REFERENCE_IMAGES,
    IMAGEN_MODEL,
)

class VeoProvider(BaseVideoProvider):
    """Video generation using Google Veo 3.1 API."""

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = load_json(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

        # Initialize client via ApiKeyManager
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

        # ElevenLabs TTS provider — instantiated once, reused across all scenes
        self.eleven_prov = ElevenLabsProvider(pod_config_path)

    def check_availability(self) -> bool:
        """Verify Veo API is accessible."""
        try:
            # Client is already initialized in __init__ via ApiKeyManager
            if self.client:
                print("[VEO] ✅ Google GenAI client inicializado correctamente")
                return True
            return False
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

        # NOTE: negative_prompt is set but Veo 3.1 silently ignores it.
        # Kept for forward compatibility if future API versions support it.
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

        model = VEO_MODEL
        print(f"[VEO]    Modelo: {model} | Duración: {duration}s | Resolución: {VEO_RESOLUTION}")

        gen_params = self._build_gen_params(
            prompt=prompt,
            mode="text",
            reference_images=reference_images,
            negative_prompt=negative_prompt,
        )
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
            frames_dir = os.path.join(os.path.dirname(save_dir), "frames")
            saved_frame_path = os.path.join(frames_dir, f"last_frame_{scene_index:02d}.png")
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

    def _generate_clip(
        self, scene: dict, i: int, clips: List[VideoClip], transition: str,
        prompt: str, scene_duration: int, ref_images: List[str],
        negative: Optional[str], narrative_phase: str, clips_dir: str,
        incoming_transition: str = "cut", is_resume_bridge: bool = False,
    ) -> VideoClip:
        """
        Generate a single clip based on the incoming transition type.
        
        Routing logic:
          - First scene: always fresh (generate_scene)
          - incoming 'continue': jump_to_scene (last frame seed, seamless)
          - incoming 'cut': jump_to_scene (last frame seed, new angle same location)
          - incoming 'scene_change': generate_scene fresh (new location entirely)
        """
        if i == 0 or not clips:
            # First scene — always generate fresh
            return self.generate_scene(
                prompt=prompt, duration=scene_duration,
                seed=scene.get("seed"), reference_images=ref_images,
                negative_prompt=negative, save_dir=clips_dir,
                scene_index=i, narrative_phase=narrative_phase,
            )
        elif incoming_transition == "continue":
            # 'continue' uses last frame as visual seed for a seamless, same-angle continuation
            return self.jump_to_scene(
                previous_clip=clips[-1], prompt=prompt,
                reference_images=ref_images, save_dir=clips_dir,
                scene_index=i, narrative_phase=narrative_phase,
            )
        else:
            # "cut" or "scene_change"
            # We CANNOT use jump_to_scene for "cut" because the image seed becomes the literal first frame.
            # If the angle changes, forcing the old angle as frame 1 causes Veo to violently 
            # jump-cut mid-clip to satisfy the text prompt.
            # Consistency is instead maintained via SceneContextManager (text) + Reference Images.
            
            # IMPROVEMENT: Use the last frame as an ADDITIONAL reference image for 'cut' transitions
            # ONLY if this is the very first clip of a resumed session (to bridge the visual gap).
            # Otherwise, rely on the base reference image to prevent API timeouts from multi-conditioning overload.
            enhanced_ref_images = list(ref_images) if ref_images else []
            if incoming_transition == "cut" and clips and is_resume_bridge:
                # For scene_index i, the previous scene was i-1, so its frame is last_frame_{i:02d}.png
                frames_dir = os.path.join(os.path.dirname(clips_dir), "frames")
                last_frame_path = os.path.join(frames_dir, f"last_frame_{i:02d}.png")
                if os.path.exists(last_frame_path) and last_frame_path not in enhanced_ref_images:
                    enhanced_ref_images.append(last_frame_path)
                    print(f"[VEO]    📸 Inyectando 'hot visual memory': {os.path.basename(last_frame_path)} como referencia para el 'cut'.")

            return self.generate_scene(
                prompt=prompt, duration=scene_duration,
                seed=scene.get("seed"), reference_images=enhanced_ref_images,
                negative_prompt=negative, save_dir=clips_dir,
                scene_index=i, narrative_phase=narrative_phase,
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
        Handle a scene generation error: retry with rotated key if rate-limited,
        or mark as failed and signal the main loop to break.

        Returns:
            dict with keys:
              - "clip": VideoClip if retry succeeded (caller should append + continue)
              - "rate_limited": True if all keys exhausted
              - If neither key is present, caller should break (non-retriable error)
        """
        error_msg = str(error)
        print(f"[VEO] ❌ Error en escena {scene_num}: {error_msg[:120]}")

        if is_rate_limit_error(error):
            if self.key_manager.rotate_key(error_msg):
                self.client = self.key_manager.get_client()
                print(f"[VEO] 🔄 Reintentando escena {scene_num} con {self.key_manager.get_key_label()} ({self.key_manager.get_active_key()})...")
                try:
                    clip = self._generate_clip(
                        scene=scene, i=i, clips=clips, transition=transition,
                        prompt=prompt, scene_duration=scene_duration,
                        ref_images=ref_images, negative=negative,
                        narrative_phase=narrative_phase, clips_dir=clips_dir,
                        incoming_transition=incoming_transition,
                        is_resume_bridge=is_resume_bridge,
                    )
                    self._apply_dubbing(clip, scene, clips_dir, scene_num_str)
                    self.key_manager.record_success()
                    print(f"[VEO] ✅ Escena {scene_num} generada con key rotada: {clip.file_path}")
                    if progress_manager:
                        progress_manager.mark_scene_completed(
                            scene_index=i, clip_path=clip.file_path, model_used=VEO_MODEL,
                        )
                    return {"clip": clip}
                except Exception as retry_e:
                    error_msg = str(retry_e)
                    print(f"[VEO] ❌ Retry también falló: {error_msg[:120]}")

            # All keys exhausted
            print(f"[VEO] 🛑 Todas las keys agotadas. Guardando progreso...")
            if progress_manager:
                progress_manager.mark_scene_failed(i, error_msg, is_rate_limit=True)
            return {"rate_limited": True}
        else:
            # Non-retriable error
            print(f"[VEO] 🛑 Error en escena {scene_num}. Guardando progreso y parando.")
            if progress_manager:
                progress_manager.mark_scene_failed(i, error_msg)
            return {}

    def _apply_dubbing(self, clip: VideoClip, scene: dict, clips_dir: str, scene_num_str: str) -> None:
        """
        Genera el doblaje final de la escena y reemplaza la pista de audio del clip.
        
        Pipeline principal (Demucs + STS):
          1. Extraer el audio nativo de Veo (lip-synced, con voz + SFX).
          2. Separar voz de efectos con Demucs (Meta).
          3. Usar ElevenLabs STS solo sobre la voz aislada.
          4. Remezclar la voz doblada con los efectos originales.
          5. Inyectar el audio final en el clip.
          
        Fallback (TTS sin SFX):
          Si falla Demucs o STS, hace Text-to-Speech clásico.
        """
        audio_text = scene.get("audio_text", "")
        character_name = scene.get("character", "")
        if not audio_text or not character_name:
            return

        audio_filename = f"dialogue_{scene_num_str}.wav"
        
        # Save dialogues to 'audio' folder if inside an episode directory structure
        parent_dir = os.path.dirname(clips_dir)
        if os.path.basename(clips_dir) == "clips":
            audio_dir = os.path.join(parent_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)
            audio_path = os.path.join(audio_dir, audio_filename)
        else:
            audio_path = os.path.join(clips_dir, audio_filename)

        final_audio_to_mix = None
        sfx_track = None  # Will hold isolated SFX from Demucs

        # --- Step 1: Extract Veo's native audio ---
        veo_audio_path = AudioMixer.extract_audio(clip.file_path)

        if veo_audio_path:
            # --- Step 2: Separate voice from SFX using Demucs ---
            separated = None
            if AudioSeparator.is_available():
                separated = AudioSeparator.separate(
                    audio_path=veo_audio_path,
                    output_dir=os.path.dirname(audio_path),
                )
            
            if separated:
                vocals_path, sfx_path = separated
                sfx_track = sfx_path  # Keep SFX for later remix
                
                # --- Step 3: STS on isolated voice only (clean, no SFX artifacts) ---
                converted_audio = self.eleven_prov.convert_voice(
                    source_audio_path=vocals_path,
                    character_name=character_name,
                    output_path=audio_path
                )
                
                if converted_audio:
                    final_audio_to_mix = converted_audio
                    print(f"[DUBBING] 🎙️ Voz STS convertida (aislada con Demucs)")
                else:
                    print(f"[DUBBING] ⚠️ STS falló sobre voz aislada, probando TTS fallback...")
                
                # Cleanup isolated vocals (already converted)
                try:
                    if os.path.exists(vocals_path):
                        os.remove(vocals_path)
                except OSError:
                    pass
            else:
                # Demucs not available or failed → fallback to raw STS
                print(f"[DUBBING] ⚠️ Demucs no disponible, usando STS sobre audio bruto...")
                converted_audio = self.eleven_prov.convert_voice(
                    source_audio_path=veo_audio_path,
                    character_name=character_name,
                    output_path=audio_path
                )
                if converted_audio:
                    final_audio_to_mix = converted_audio
                    print(f"[DUBBING] 🎙️ Audio STS convertido (sin separación)")
            
            # Cleanup extracted native audio
            try:
                os.remove(veo_audio_path)
            except OSError:
                pass

        # --- Fallback: Text-to-Speech (TTS) ---
        if not final_audio_to_mix:
            generated_audio = self.eleven_prov.generate_dialogue(audio_text, character_name, audio_path)
            if generated_audio:
                final_audio_to_mix = generated_audio
                print(f"[DUBBING] 🎙️ Audio TTS generado exitosamente")

        # --- Step 4: Remix dubbed voice with original SFX ---
        if final_audio_to_mix and sfx_track and os.path.exists(sfx_track):
            remixed_path = audio_path.replace(".wav", "_remixed.wav")
            remixed = AudioSeparator.remix_voice_with_sfx(
                dubbed_voice_path=final_audio_to_mix,
                sfx_path=sfx_track,
                output_path=remixed_path,
                voice_volume=1.0,
                sfx_volume=0.7,
            )
            if remixed:
                final_audio_to_mix = remixed
                print(f"[DUBBING] 🔊 Voz doblada + efectos originales remezclados")
            
            # Cleanup SFX track
            try:
                os.remove(sfx_track)
            except OSError:
                pass

        # --- Step 5: Mix the final dubbing audio back into the video ---
        if final_audio_to_mix:
            mixed_path = clip.file_path.replace(".mp4", "_dubbed.mp4")
            final_clip_path = AudioMixer.mix_audio_to_video(
                video_path=clip.file_path,
                audio_path=final_audio_to_mix,
                output_path=mixed_path,
                audio_volume=1.0
            )
            
            if final_clip_path and final_clip_path != clip.file_path:
                clip.dubbed_path = final_clip_path
                print(f"[DUBBING] ✅ Audio de {character_name} inyectado al clip {scene_num_str} (Guardado en {os.path.basename(final_clip_path)})")

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
        # Load character reference images
        ref_images = []
        consistency_cfg = self.config.get("consistency", {})
        if consistency_cfg.get("generate_anchor_images", False) and episode_dir:
            # Phase 4: Generate dynamic anchor image for the episode
            anchor_path = self._generate_anchor_image(episode_dir, script, scenes)
            if anchor_path:
                ref_images = [anchor_path]
        
        # Fallback to static config images if anchor generation disabled or failed
        if not ref_images:
            ref_images = self._get_character_reference_images()
        # Collect clips — load previously generated clips if resuming
        clips: List[VideoClip] = []
        if resume_from > 0 and progress_manager:
            completed = progress_manager.get_completed_clips()
            for c in completed:
                if c.get("clip_path") and os.path.exists(c["clip_path"]):
                    clip_path = c["clip_path"]
                    expected_dubbed = clip_path.replace(".mp4", "_dubbed.mp4")
                    dubbed_path = expected_dubbed if os.path.exists(expected_dubbed) else None
                    clips.append(VideoClip(
                        file_path=clip_path,
                        duration=c.get("duration_seconds", VEO_DURATION_SECONDS),
                        dubbed_path=dubbed_path,
                    ))
            print(f"[VEO]    📂 {len(clips)} clips previos recuperados")

        rate_limited = False

        # Scene Context Manager — tracks location, props, character state for consistency
        context_mgr = SceneContextManager(episode_dir or clips_dir, pod_config=self.config)

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)

            # Skip already completed scenes
            if i < resume_from:
                continue

            narrative_phase = scene.get("narrative_phase", "")
            # The transition that LED to this scene (from previous scene's transition_to_next)
            incoming_transition = scenes[i - 1].get("transition_to_next", "cut") if i > 0 else "scene_change"
            # Get continuity context from previous scenes
            continuity_context = context_mgr.get_continuity_context(incoming_transition)
            prompt = self._build_cinematographic_prompt(
                scene, narrative_phase,
                incoming_transition=incoming_transition,
                continuity_context=continuity_context,
            )
            negative = scene.get("negative_prompt")
            transition = scene.get("transition_to_next", "cut")
            scene_duration = scene.get("duration_seconds", VEO_DURATION_SECONDS)
            # Clamp to valid range (4-8)
            scene_duration = max(4, min(scene_duration, VEO_DURATION_SECONDS))

            print(f"\n--- Escena {scene_num}/{len(scenes)} ({scene_duration}s) ---")

            try:
                scene_num_str = f"{scene_num:02d}"

                clip = self._generate_clip(
                    scene=scene, i=i, clips=clips, transition=transition,
                    prompt=prompt, scene_duration=scene_duration,
                    ref_images=ref_images, negative=negative,
                    narrative_phase=narrative_phase, clips_dir=clips_dir,
                    incoming_transition=incoming_transition,
                    is_resume_bridge=(i == resume_from and resume_from > 0),
                )

                self._apply_dubbing(clip, scene, clips_dir, scene_num_str)

                clips.append(clip)
                print(f"[VEO] ✅ Escena {scene_num} generada: {clip.file_path}")
                self.key_manager.record_success()

                # Save last frame for resume safety
                self._save_last_frame(clip.file_path, clips_dir, i)

                # Update scene context for next clip's consistency
                context_mgr.update_after_scene(i, scene, transition)

                # Persist progress
                if progress_manager:
                    progress_manager.mark_scene_completed(
                        scene_index=i,
                        clip_path=clip.file_path,
                        model_used=VEO_MODEL,
                    )

            except Exception as e:
                result = self._handle_scene_error(
                    e, i=i, scene=scene, scene_num=scene_num,
                    clips=clips, transition=transition, prompt=prompt,
                    scene_duration=scene_duration, ref_images=ref_images,
                    negative=negative, narrative_phase=narrative_phase,
                    clips_dir=clips_dir, scene_num_str=scene_num_str,
                    progress_manager=progress_manager,
                    incoming_transition=incoming_transition,
                    is_resume_bridge=(i == resume_from and resume_from > 0),
                )
                if result.get("clip"):
                    clips.append(result["clip"])
                    continue
                if result.get("rate_limited"):
                    rate_limited = True
                break

        # Final result
        if not clips:
            error_msg = "No se generó ningún clip."
            if progress_manager:
                progress_manager.mark_episode_failed(error_msg)
            raise RuntimeError(error_msg)

        # Concatenate clips
        if len(clips) == 1:
            final_native_path = clips[0].file_path
            final_dubbed_path = getattr(clips[0], 'dubbed_path', None) or final_native_path
        else:
            final_native_path = self._concatenate_clips(clips, output_path, use_dubbed=False)
            
            # Form final dubbed path
            output_dir = os.path.dirname(output_path)
            base_name = os.path.basename(output_path).replace(".mp4", "_dubbed.mp4")
            dubbed_output_path = os.path.join(output_dir, base_name)
            final_dubbed_path = self._concatenate_clips(clips, dubbed_output_path, use_dubbed=True)

        # Update progress
        if progress_manager:
            if rate_limited:
                print(f"\n[VEO] ⏸️  Episodio pausado por rate limit. Resume con --resume")
                print(progress_manager.get_status_summary())
            elif len(clips) >= len(scenes):
                # ALL scenes completed successfully
                progress_manager.mark_episode_completed(final_native_path)
            else:
                # Partial generation (stopped by error) — don't mark as completed
                print(f"\n[VEO] ⏸️  Episodio parcial ({len(clips)}/{len(scenes)} clips). Resume con opción 4.")
                print(progress_manager.get_status_summary())

        completed_count = len(clips)
        total_count = len(scenes)
        status = "PARCIAL" if completed_count < total_count else "COMPLETO"

        print(f"\n{'='*60}")
        print(f"[VEO] {'⏸️' if rate_limited else '✅'} Vídeo {status}:")
        print(f"[VEO]    Nativo:  {final_native_path}")
        if final_dubbed_path != final_native_path:
            print(f"[VEO]    Doblado: {final_dubbed_path}")
        print(f"[VEO]    Clips generados: {completed_count}/{total_count}")
        print(f"{'='*60}\n")

        return final_dubbed_path

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
                raise TimeoutError(f"Operación excedió timeout de {VEO_TIMEOUT}s")
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
                print(f"[VEO]    📷 Último frame guardado en frames/: {os.path.basename(frame_path)}")
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

    def _generate_anchor_image(self, episode_dir: str, script: dict, scenes: list) -> Optional[str]:
        """
        Phase 4: Generate an episode-specific reference image (Anchor Image) using Imagen 3.
        This provides Veo with a character reference that already matches the episode's
        environment and lighting, maximizing consistency.
        """
        anchor_path = os.path.join(episode_dir, "anchor_image.png")
        if os.path.exists(anchor_path):
            print(f"[VEO]    📸 Usando Anchor Image existente: {anchor_path}")
            return anchor_path
            
        print(f"[VEO]    🎨 Generando Anchor Image del episodio con Imagen 3...")
        
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
                print(f"[VEO]    ✅ Anchor Image generada y guardada en {anchor_path}")
                return anchor_path
                
        except Exception as e:
            print(f"[VEO] ⚠️ Error generando Anchor Image: {e}")
            
        return None

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

    @staticmethod
    def _sanitize_visual_prompt(visual_prompt: str) -> str:
        """
        Strip dialogue text that Gemini sometimes embeds inside visual_prompt.
        
        Patterns removed:
          - 'The squirrel says "¡Hola, exploradores!"'
          - 'The character says "text"'
          - Any 'X says "..."' pattern with quoted Spanish/English text
          
        This does NOT affect the audio_text injection (line ~793) which feeds
        Veo's native lip-sync. Only cleans contamination from script generation.
        """
        if not visual_prompt:
            return visual_prompt
        
        # Remove patterns like: The squirrel says "..." or The character says "..."
        # Handles escaped quotes and Spanish characters
        cleaned = re.sub(
            r'The \w+ says\s*"[^"]*"\s*\.?\s*',
            '',
            visual_prompt,
            flags=re.IGNORECASE,
        )
        
        # Also handle escaped quote variants from JSON
        cleaned = re.sub(
            r'The \w+ says\s*\\"[^"]*\\"\s*\.?\s*',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )

        # Clean up any double spaces or trailing dots left behind
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        cleaned = re.sub(r'\.\s*\.', '.', cleaned)
        
        return cleaned

    def _build_cinematographic_prompt(
        self, scene: dict, narrative_phase: str = "",
        incoming_transition: str = "cut", continuity_context: str = None,
    ) -> str:
        """
        Build a detailed cinematographic prompt from scene metadata.
        Combines visual_prompt with camera, mood, lighting, and audio info.
        Injects defensive guards based on the incoming transition type.
        Optionally injects continuity context from SceneContextManager.
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

        # Main visual prompt — sanitize dialogue contamination before using
        visual_prompt = scene.get("visual_prompt", "")
        visual_prompt = self._sanitize_visual_prompt(visual_prompt)
        parts.append(visual_prompt)

        # Continuity context from SceneContextManager (Phase 3)
        if continuity_context:
            parts.append(continuity_context)

        # Audio/dialogue with voice direction
        character_name = scene.get("character", "")
        audio_text = scene.get("audio_text", "")
        voice_direction = scene.get("voice_direction", "")

        if audio_text:
            # Default fallback if character not found or not mapped
            voice_desc = "young cheerful male voice, European Spanish"
            display_name = "Narrador"

            if character_name:
                display_name = character_name
                # Find character in config to extract detailed voice profile
                for char_config in self.config.get("characters", []):
                    if char_config.get("name", "").lower() == character_name.lower():
                        if "voice_description" in char_config:
                            voice_desc = char_config["voice_description"]
                        break
            
            # Combine config voice description with scene-specific direction if present
            final_voice_modifier = f"{voice_desc}, {voice_direction}" if voice_direction else voice_desc

            parts.append(f'[AUDIO ONLY INSTRUCTION - DO NOT CHANGE VISUAL APPEARANCE] The character {display_name} speaks with a voice described as: "{final_voice_modifier}" and says: "{audio_text}"')

            # Anti-gibberish guard: prevent Veo from generating mumbling/creepy sounds
            # after the spoken line ends. The clip may be longer than the speech.
            parts.append("After the character finishes speaking, only natural ambient sounds "
                         "(wind, birds, rustling leaves, water). Absolutely no mumbling, "
                         "no babbling, no additional vocalizations after the dialogue line ends")

        # Art style from config
        art_style = self.config.get("consistency", {}).get("art_style", "")
        if art_style:
            parts.append(art_style)

        # --- Defensive guards based on incoming transition ---
        if incoming_transition == "continue":
            # This scene will be generated via jump_to_scene (image-to-video from last frame).
            # Veo tends to "morph" from the seed frame to the new prompt if they differ.
            # We inject a strong continuity instruction to prevent this.
            parts.append("This shot is a smooth, uninterrupted continuation of the previous shot. "
                         "Maintain the exact same character position, props, background, lighting, "
                         "and camera angle. Do not introduce any new objects or change the scene. "
                         "The action flows seamlessly as if this is one continuous take")
        elif incoming_transition == "cut":
            # 'cut' = same location, different camera angle. Last frame used as seed.
            # We tell Veo to keep the environment but allow camera/action changes.
            parts.append("This is a new camera angle within the same scene. "
                         "Maintain the exact same location, environment, props, and lighting. "
                         "The character's appearance, clothing, and accessories must remain identical. "
                         "Only the camera angle, framing, or character action changes")

        # Anatomy stabilization — always appended
        parts.append("Character anatomy must remain stable and consistent throughout the entire clip. "
                     "Hands, fingers and limbs must not deform, multiply or teleport")

        # Anti-subtitle/anti-text guard — always appended
        parts.append("Absolutely no text, no subtitles, no letters, no watermarks, no written words on screen")

        return ". ".join(filter(None, parts))

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str, use_dubbed: bool = False) -> str:
        """
        Concatenate multiple video clips into one final video.
        Uses ffmpeg via subprocess for reliability.
        Includes a normalization step to ensure all clips have identical audio streams (AAC 44.1kHz).
        """
        try:
            print("[VEO] 🔄 Normalizando pistas de audio (inyectando silencio si es necesario) para concatenar...")
            normalized_paths = []
            
            for i, clip in enumerate(clips):
                if use_dubbed and getattr(clip, 'dubbed_path', None) and os.path.exists(clip.dubbed_path):
                    p = clip.dubbed_path
                else:
                    p = clip.file_path
                    
                norm_path = os.path.join(self.assets_dir, f"_norm_{i}_{int(time.time())}.mp4")
                
                # Validar si el clip tiene pista de audio
                from src.utils.audio_mixer import AudioMixer
                has_audio = AudioMixer._probe_has_audio(p)
                
                if has_audio:
                    # Re-codificamos el audio a aac y copiamos video para estandarizar
                    cmd = [
                        "ffmpeg", "-y", "-i", p,
                        "-c:v", "copy", "-c:a", "aac", "-ac", "2", "-ar", "44100",
                        norm_path
                    ]
                else:
                    # El clip no tiene audio, inyectamos una pista de silencio AAC
                    cmd = [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-i", p,
                        "-map", "1:v", "-map", "0:a",
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                        norm_path
                    ]
                
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if os.path.exists(norm_path):
                    normalized_paths.append(norm_path)
                else:
                    normalized_paths.append(p) # fallback
            
            # Create concat file list for ffmpeg
            concat_list_path = os.path.join(self.assets_dir, "_concat_list.txt")
            with open(concat_list_path, "w") as f:
                for p in normalized_paths:
                    abs_path = os.path.abspath(p)
                    safe_path = abs_path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            # Run ffmpeg concat
            print("[VEO] 🔄 Pegando todos los clips normalizados...")
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

            # Cleanup temp normalization files
            for p in normalized_paths:
                if "_norm_" in p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass
            if os.path.exists(concat_list_path):
                os.remove(concat_list_path)

            if result.returncode != 0:
                print(f"[VEO] ⚠️  ffmpeg error al concatenar:\n{result.stderr[-500:]}")
                return clips[0].file_path

            return output_path

        except FileNotFoundError:
            print("[VEO] ⚠️  ffmpeg no encontrado. Retornando primer clip.")
            return clips[0].file_path
