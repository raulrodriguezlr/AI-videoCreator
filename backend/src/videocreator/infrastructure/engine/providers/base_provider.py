"""
BaseVideoProvider — Abstract base class for all video generation providers.

Every provider must implement these atomic methods:
- generate_scene: Creates a single video clip from a text prompt.
- extend_scene: Extends an existing video clip by generating additional footage.
- jump_to_scene: Creates a new scene using the last frame of the previous clip as seed.
- generate_full_video: Orchestrates the full video generation from a script.
- check_availability: Verifies the provider is ready to use.
"""

import re
import os
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import structlog

log = structlog.get_logger(__name__)


class VideoClip:
    """Represents a generated video clip with its metadata."""

    def __init__(
        self,
        file_path: str,
        duration: float,
        seed: Optional[int] = None,
        operation_name: Optional[str] = None,
        video_ref: Any = None,
        dubbed_path: Optional[str] = None,
    ):
        self.file_path = file_path
        self.duration = duration
        self.seed = seed
        self.operation_name = operation_name
        self.video_ref = video_ref  # Provider-specific reference (e.g., Veo video object)
        self.dubbed_path = dubbed_path


class BaseVideoProvider(ABC):
    """Abstract base for all video providers."""

    def __init__(self, pod_config_path: str):
        self.pod_config_path = pod_config_path

    @abstractmethod
    def generate_scene(
        self,
        prompt: str,
        duration: int = 8,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
    ) -> VideoClip:
        """
        Generate a single video clip from a text prompt.

        Args:
            prompt: Cinematographic text prompt for the scene.
            duration: Duration in seconds (4, 6, or 8 for Veo).
            seed: Optional seed for reproducibility.
            reference_images: Optional list of image paths for character consistency.
            negative_prompt: Things to avoid in the generation.

        Returns:
            VideoClip with the generated video file path and metadata.
        """
        pass

    @abstractmethod
    def extend_scene(
        self,
        video_clip: VideoClip,
        prompt: str,
    ) -> VideoClip:
        """
        Extend an existing video clip with additional footage.
        The extended footage continues the same scene seamlessly.

        Args:
            video_clip: The previous VideoClip to extend.
            prompt: Prompt describing what happens next in the same scene.

        Returns:
            VideoClip with the extended video (original + extension).
        """
        pass

    @abstractmethod
    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
    ) -> VideoClip:
        """
        Create a new scene using the last frame of the previous clip as seed.
        This creates a "hard cut" to a new scene while maintaining visual consistency.

        Args:
            previous_clip: The previous VideoClip (last frame will be extracted).
            prompt: Prompt describing the new scene.
            reference_images: Optional reference images for consistency.

        Returns:
            VideoClip with the new scene.
        """
        pass

    # ======================================================================
    # SHARED SCENE-BUILDER PIPELINE
    # ----------------------------------------------------------------------
    # The one render loop for every provider (ported from the Veo pipeline,
    # the "perfect" v2.1.0 version). It is a template method: the loop is fixed,
    # but each provider specialises behaviour by overriding the hooks below
    # (transition dispatch, dubbing, error handling, concat...). A provider that
    # overrides nothing gets a sensible default (no dub, simple concat, mark-and-
    # stop on error). Providers may still override generate_full_video wholesale.
    # ======================================================================

    # Per-scene duration bounds (a provider may override).
    DEFAULT_SCENE_DURATION = 8
    MIN_SCENE_DURATION = 4
    LOG_TAG = "[ENGINE]"

    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
        episode_dir: str = None,
        resume_from: int = 0,
        progress_manager=None,
    ) -> str:
        """Orchestrate full video generation from a script (shared Scene Builder).

        Generates one clip per scene (first = fresh, then transition-aware), dubs
        it (hook), tracks visual continuity, persists progress, and concatenates a
        native and a dubbed final. Resilient: a failed scene is routed to the
        error hook (retry/skip/stop). Returns the dubbed final path (== native
        when the provider doesn't dub).
        """
        from videocreator.infrastructure.engine.utils.scene_context import (
            SceneContextManager,
        )

        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("El script no tiene escenas.")

        title = script.get("title", "Untitled")
        log.info("scene_builder.start", provider=self.LOG_TAG, title=title, scene_count=len(scenes), resume_from=resume_from)

        clips_dir = self._scene_save_dir(episode_dir)
        ref_images = self._collect_reference_images(episode_dir, script, scenes)

        clips: List[VideoClip] = self._restore_completed_clips(resume_from, progress_manager)
        rate_limited = False
        first_error: Exception | None = None
        context_mgr = SceneContextManager(episode_dir or clips_dir, pod_config=getattr(self, "config", {}))

        for i, scene in enumerate(scenes):
            self._current_scene_index = i
            self._total_scenes = len(scenes)
            scene_num = scene.get("scene_number", i + 1)
            if i < resume_from:
                continue

            narrative_phase = scene.get("narrative_phase", "")
            incoming_transition = (
                scenes[i - 1].get("transition_to_next", "cut") if i > 0 else "scene_change"
            )
            continuity_context = context_mgr.get_continuity_context(incoming_transition)
            prompt = self._build_cinematographic_prompt(
                scene, narrative_phase,
                incoming_transition=incoming_transition,
                continuity_context=continuity_context,
            )
            negative = scene.get("negative_prompt")
            transition = scene.get("transition_to_next", "cut")
            scene_duration = scene.get("duration_seconds", self.DEFAULT_SCENE_DURATION)
            scene_duration = max(self.MIN_SCENE_DURATION, min(scene_duration, self.DEFAULT_SCENE_DURATION))
            scene_num_str = f"{scene_num:02d}"

            log.info("scene_builder.scene_start", scene=scene_num, total=len(scenes), duration_s=scene_duration)
            try:
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
                log.info("scene_builder.scene_ready", provider=self.LOG_TAG, scene=scene_num, path=clip.file_path)
                self._on_clip_success()
                self._save_last_frame(clip.file_path, clips_dir, i)
                context_mgr.update_after_scene(i, scene, transition)
                if progress_manager:
                    progress_manager.mark_scene_completed(
                        scene_index=i, clip_path=clip.file_path, model_used=self._model_label(),
                    )
            except Exception as e:  # noqa: BLE001 — routed to the error hook
                if first_error is None:
                    first_error = e
                result = self._handle_scene_error(
                    e, i=i, scene=scene, scene_num=scene_num, clips=clips,
                    transition=transition, prompt=prompt, scene_duration=scene_duration,
                    ref_images=ref_images, negative=negative,
                    narrative_phase=narrative_phase, clips_dir=clips_dir,
                    scene_num_str=scene_num_str, progress_manager=progress_manager,
                    incoming_transition=incoming_transition,
                    is_resume_bridge=(i == resume_from and resume_from > 0),
                )
                if result.get("clip"):
                    clips.append(result["clip"])
                    continue
                if result.get("rate_limited"):
                    rate_limited = True
                break

        if not clips:
            # Include the actual error so it propagates to the caller
            detail = str(first_error) if first_error else "unknown error"
            if progress_manager:
                progress_manager.mark_episode_failed(f"No se generó ningún clip: {detail}")
            raise RuntimeError(f"No se generó ningún clip: {detail}")

        # Partial render (a scene was filtered/failed or we hit a rate limit): do
        # NOT present it as a finished episode. Mark it resumable and raise so the
        # caller flags the episode FAILED — the per-scene progress is saved, so
        # 'Continuar' (resume) picks up from the last good scene instead of leaving
        # a half-episode that looks done.
        if len(clips) < len(scenes):
            reason = ("rate limit" if rate_limited
                      else str(first_error) if first_error else "una escena falló/fue filtrada")
            log.warning("scene_builder.partial", provider=self.LOG_TAG,
                        clips=len(clips), total=len(scenes), reason=reason)
            if progress_manager:
                progress_manager.mark_episode_failed(
                    f"render incompleto: {len(clips)}/{len(scenes)} escenas ({reason})"
                )
            raise RuntimeError(
                f"render incompleto: {len(clips)}/{len(scenes)} escenas ({reason}). "
                "Usa 'Continuar' para reanudar desde la última escena buena."
            )

        final_native_path, final_dubbed_path = self._assemble_finals(clips, output_path)
        if progress_manager:
            progress_manager.mark_episode_completed(final_native_path)
        log.info(
            "scene_builder.done", provider=self.LOG_TAG, status="COMPLETO",
            native=final_native_path,
            dubbed=final_dubbed_path if final_dubbed_path != final_native_path else None,
            clips=len(clips), total=len(scenes),
        )
        return final_dubbed_path

    # ---- pipeline steps (small, overridable) ------------------------------
    def _scene_save_dir(self, episode_dir: Optional[str]) -> str:
        if episode_dir:
            clips_dir = os.path.join(episode_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
            return clips_dir
        return getattr(self, "assets_dir", episode_dir or ".")

    def _restore_completed_clips(self, resume_from: int, progress_manager) -> List["VideoClip"]:
        """Reload clips already rendered in a previous (interrupted) run."""
        clips: List[VideoClip] = []
        if resume_from > 0 and progress_manager:
            for c in progress_manager.get_completed_clips():
                path = c.get("clip_path")
                if path and os.path.exists(path):
                    dubbed = path.replace(".mp4", "_dubbed.mp4")
                    clips.append(VideoClip(
                        file_path=path,
                        duration=c.get("duration_seconds", self.DEFAULT_SCENE_DURATION),
                        dubbed_path=dubbed if os.path.exists(dubbed) else None,
                    ))
            log.info("scene_builder.clips_restored", provider=self.LOG_TAG, count=len(clips))
        return clips

    def _assemble_finals(self, clips: List["VideoClip"], output_path: str) -> tuple:
        """Concatenate the native final and, only if any clip was dubbed, a dubbed
        final. Providers that don't dub get dubbed == native (no spurious file)."""
        has_dub = any(getattr(c, "dubbed_path", None) for c in clips)
        if len(clips) == 1:
            native = clips[0].file_path
            return native, (getattr(clips[0], "dubbed_path", None) or native)
        native = self._concatenate_clips(clips, output_path, use_dubbed=False)
        if not has_dub:
            return native, native
        dubbed_out = output_path.replace(".mp4", "_dubbed.mp4")
        return native, self._concatenate_clips(clips, dubbed_out, use_dubbed=True)

    # ---- hooks (defaults; providers override "a su manera") ---------------
    def _collect_reference_images(self, episode_dir, script, scenes):
        """Veo refs: a dynamic anchor image if enabled, else static character refs."""
        ref_images = []
        consistency_cfg = getattr(self, "config", {}).get("consistency", {})
        if consistency_cfg.get("generate_anchor_images", False) and episode_dir:
            anchor_path = self._generate_anchor_image(episode_dir, script, scenes)
            if anchor_path:
                ref_images = [anchor_path]
        if not ref_images:
            ref_images = self._get_character_reference_images()
        return ref_images


    def _generate_anchor_image(self, episode_dir, script, scenes):
        """Generate a dynamic anchor reference image for the episode.

        Default: unsupported (returns None) -> falls back to static character
        reference images. Providers with an image model (e.g. Veo/Imagen) override.
        """
        return None

    def _get_character_reference_images(self) -> List[str]:
        """Resolve character reference images from the pod config (on disk).

        Each character may have several (`reference_images`); `reference_image`
        (singular) is honoured too. Paths resolve relative to the pod dir.
        """
        ref_images: List[str] = []
        pod_dir = getattr(self, "pod_dir", "")
        for char in self.config.get("characters", []):
            paths = list(char.get("reference_images") or [])
            single = char.get("reference_image")
            if single and single not in paths:
                paths.append(single)
            for ref_path in paths:
                full = os.path.join(pod_dir, ref_path)
                if os.path.exists(full) and full not in ref_images:
                    ref_images.append(full)
        return ref_images

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
                    log.info("scene_builder.hot_visual_memory", frame=os.path.basename(last_frame_path))

            return self.generate_scene(
                prompt=prompt, duration=scene_duration,
                seed=scene.get("seed"), reference_images=enhanced_ref_images,
                negative_prompt=negative, save_dir=clips_dir,
                scene_index=i, narrative_phase=narrative_phase,
            )

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
        from videocreator.infrastructure.engine.utils.audio_mixer import AudioMixer
        from videocreator.infrastructure.engine.utils.audio_separator import AudioSeparator
        audio_text = scene.get("audio_text", "")
        character_name = scene.get("character", "")
        if not audio_text:
            return
        if not character_name:
            # Narrator fallback: scenes with narration but no assigned
            # character get dubbed with the default voice (one consistent
            # narrator across the whole video) instead of silently delegating
            # to the provider's native audio. The unknown name resolves to
            # ELEVENLABS_DEFAULT_VOICE_ID via voice_map.get(..., DEFAULT).
            character_name = "Narrador"
            log.info("dubbing.narrator_fallback", scene=scene_num_str)

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
                converted_audio = self._eleven().convert_voice(
                    source_audio_path=vocals_path,
                    character_name=character_name,
                    output_path=audio_path
                )
                
                if converted_audio:
                    final_audio_to_mix = converted_audio
                    log.info("dubbing.sts_converted_demucs")
                else:
                    log.warning("dubbing.sts_failed_demucs_fallback_tts")
                
                # Cleanup isolated vocals (already converted)
                try:
                    if os.path.exists(vocals_path):
                        os.remove(vocals_path)
                except OSError:
                    pass
            else:
                # Demucs not available or failed → fallback to raw STS
                log.warning("dubbing.demucs_unavailable_raw_sts")
                converted_audio = self._eleven().convert_voice(
                    source_audio_path=veo_audio_path,
                    character_name=character_name,
                    output_path=audio_path
                )
                if converted_audio:
                    final_audio_to_mix = converted_audio
                    log.info("dubbing.sts_converted_raw")
            
            # Cleanup extracted native audio
            try:
                os.remove(veo_audio_path)
            except OSError:
                pass

        # --- Fallback: Text-to-Speech (TTS) ---
        if not final_audio_to_mix:
            generated_audio = self._eleven().generate_dialogue(audio_text, character_name, audio_path)
            if generated_audio:
                final_audio_to_mix = generated_audio
                log.info("dubbing.tts_generated")

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
                log.info("dubbing.voice_sfx_remixed")
            
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
                log.info("dubbing.audio_injected", character=character_name, scene=scene_num_str, path=os.path.basename(final_clip_path))

    # ==========================================
    # SCENE-BUILDER HOOKS (shared loop in BaseVideoProvider)
    # ==========================================

    def _eleven(self):
        """Lazily build/cache the ElevenLabs provider used for dubbing."""
        prov = getattr(self, "eleven_prov", None)
        if prov is None:
            from videocreator.infrastructure.engine.providers.elevenlabs_provider import (
                ElevenLabsProvider,
            )
            prov = ElevenLabsProvider(self.pod_config_path)
            self.eleven_prov = prov
        return prov

    def _on_clip_success(self) -> None:
        """Called after each successful clip (e.g. to record API-key health)."""
        return None

    def _model_label(self) -> str:
        """Model id recorded in progress (override per provider)."""
        return getattr(self, "_model", None) or "model"

    def _handle_scene_error(self, error: Exception, *, i: int, progress_manager=None, **kwargs) -> dict:
        """Default error policy: persist failure and stop (return {} → break)."""
        error_text = str(error)
        log.error("scene_builder.scene_error", provider=self.LOG_TAG, scene=i + 1, error=error_text[:400])
        if progress_manager:
            progress_manager.mark_scene_failed(i, error_text)
        return {}

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str, use_dubbed: bool = False) -> str:
        """
        Concatenate multiple video clips into one final video.
        Uses ffmpeg via subprocess for reliability.
        Includes a normalization step to ensure all clips have identical audio streams (AAC 44.1kHz).
        """
        try:
            log.info("concat.normalizing_audio")
            normalized_paths = []
            
            for i, clip in enumerate(clips):
                if use_dubbed and getattr(clip, 'dubbed_path', None) and os.path.exists(clip.dubbed_path):
                    p = clip.dubbed_path
                else:
                    p = clip.file_path
                    
                norm_path = os.path.join(self.assets_dir, f"_norm_{i}_{int(time.time())}.mp4")
                
                # Validar si el clip tiene pista de audio
                from videocreator.infrastructure.engine.utils.audio_mixer import AudioMixer
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
            def run_concat(paths, out_path):
                concat_list_path = os.path.join(self.assets_dir, f"_concat_list_{int(time.time()*1000)}.txt")
                with open(concat_list_path, "w") as f:
                    for p in paths:
                        safe_path = os.path.abspath(p).replace("\\", "/")
                        f.write(f"file '{safe_path}'\n")
                res = subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", out_path],
                    capture_output=True, text=True
                )
                if os.path.exists(concat_list_path):
                    try: os.remove(concat_list_path)
                    except: pass
                return res

            # Run ffmpeg concat
            log.info("concat.joining_clips")
            result = run_concat(normalized_paths, output_path)

            if result.returncode != 0:
                log.warning("concat.ffmpeg_error", stderr=result.stderr[-500:])
                log.info("concat.fallback_mode", msg="Attempting to identify and skip bad clips")
                
                valid_paths = [normalized_paths[0]] if normalized_paths else []
                for p in normalized_paths[1:]:
                    test_out = output_path + ".test.mp4"
                    test_res = run_concat(valid_paths + [p], test_out)
                    if test_res.returncode == 0:
                        valid_paths.append(p)
                    else:
                        log.warning("concat.skipping_bad_clip", clip=p)
                    if os.path.exists(test_out):
                        try: os.remove(test_out)
                        except: pass
                        
                if len(valid_paths) > 0 and len(valid_paths) < len(normalized_paths):
                    log.info("concat.retrying_without_bad_clips")
                    result = run_concat(valid_paths, output_path)

            # Cleanup temp normalization files
            for p in normalized_paths:
                if "_norm_" in p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass

            if result.returncode != 0:
                log.warning("concat.fallback_failed")
                return clips[0].dubbed_path if (use_dubbed and getattr(clips[0], 'dubbed_path', None)) else clips[0].file_path

            return output_path

        except FileNotFoundError:
            log.warning("concat.ffmpeg_not_found")
            return clips[0].dubbed_path if (use_dubbed and getattr(clips[0], 'dubbed_path', None)) else clips[0].file_path

    def _save_last_frame(self, video_path: str, clips_dir: str, scene_index: int) -> None:
        """Persist the last frame as frames/last_frame_NN.png (resume/i2v seed)."""
        try:
            import cv2  # lazy: optional/heavy dep
        except ImportError:
            return
        frames_dir = os.path.join(os.path.dirname(clips_dir), "frames")
        os.makedirs(frames_dir, exist_ok=True)
        try:
            cap = cv2.VideoCapture(video_path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                cap.release()
                return
            cap.set(cv2.CAP_PROP_POS_FRAMES, total - 1)
            ok, frame = cap.read()
            cap.release()
            if ok:
                cv2.imwrite(os.path.join(frames_dir, f"last_frame_{scene_index + 1:02d}.png"), frame)
        except Exception as e:  # noqa: BLE001
            log.warning("scene_builder.last_frame_save_failed", provider=self.LOG_TAG, error=str(e))

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

    @abstractmethod
    def check_availability(self) -> bool:
        """
        Verify this provider is available and ready to use.

        Returns:
            True if the provider can generate videos, False otherwise.
        """
        pass
