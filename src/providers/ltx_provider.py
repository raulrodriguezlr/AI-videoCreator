"""
LtxProvider — Local video generation using LTX-2 via Lightricks ltx-pipelines.

Implements BaseVideoProvider with the same Scene Builder logic as VeoProvider:
- generate_scene: Text-to-video
- jump_to_scene: Last frame → image-to-video
- extend_scene: Stub (LTX-2 doesn't support native extend, falls back to jump_to)
- generate_full_video: Full Scene Builder loop with progress/resume/error handling
- _build_cinematographic_prompt: Same prompt building (minus audio — LTX handles that)
- _concatenate_clips: Same ffmpeg concat

LTX-2 generates synchronized audio+video natively.
"""

import os
import json
import subprocess
import logging
import time
from typing import Optional, List, Dict, Any

from src.providers.base_provider import BaseVideoProvider, VideoClip
from src.engines.ltx_engine import LtxEngine
from src.variables import (
    LTX_MODELS_DIR,
    LTX_CHECKPOINT,
    LTX_TEXT_ENCODER,
    LTX_DISTILLED_LORA,
    LTX_QUANTIZATION,
    LTX_WIDTH,
    LTX_HEIGHT,
    LTX_NUM_FRAMES,
    LTX_FRAME_RATE,
    LTX_INFERENCE_STEPS,
    LTX_DURATION_SECONDS,
    LTX_NEGATIVE_PROMPT,
)

logger = logging.getLogger(__name__)


class LtxProvider(BaseVideoProvider):
    """Local video generation using LTX-2 v2 (ltx-pipelines oficial)."""

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

        # Initialize the LTX Engine (lazy load — pipeline loads on first use)
        self.engine = LtxEngine(
            checkpoint_path=os.path.join(LTX_MODELS_DIR, LTX_CHECKPOINT),
            gemma_root=os.path.join(LTX_MODELS_DIR, LTX_TEXT_ENCODER),
            distilled_lora_path=os.path.join(LTX_MODELS_DIR, LTX_DISTILLED_LORA),
            quantization=LTX_QUANTIZATION
        )

    def _load_config(self, path: str) -> dict:
        """Load pod configuration from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_availability(self) -> bool:
        """Verify CUDA and local model files are accessible."""
        available = self.engine.check_availability()
        if available:
            print("[LTX] ✅ LTX-2 engine ready (local GPU)")
        else:
            print("[LTX] ❌ LTX-2 not available — check CUDA and model paths")
        return available

    # ==========================================
    # SCENE GENERATION METHODS
    # ==========================================

    def generate_scene(
        self,
        prompt: str,
        duration: int = LTX_DURATION_SECONDS,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
        save_dir: Optional[str] = None,
        scene_index: Optional[int] = None,
        narrative_phase: str = "",
    ) -> VideoClip:
        """Generate a single video clip using LTX-2 text-to-video."""
        print(f"[LTX] 🎬 Generando escena: '{prompt[:80]}...'")
        print(f"[LTX]    {LTX_WIDTH}x{LTX_HEIGHT} | {LTX_NUM_FRAMES} frames | {LTX_INFERENCE_STEPS} steps")

        # Build output path
        target_dir = save_dir if save_dir else self.assets_dir
        if scene_index is not None:
            filename = f"clip_{scene_index + 1:02d}.mp4"
        else:
            safe_name = prompt[:40].replace(" ", "_").replace("'", "").replace('"', "")
            filename = f"scene_{safe_name}_{int(time.time())}.mp4"
        output_path = os.path.join(target_dir, filename)

        # Generate
        actual_seed = seed if seed is not None else 42
        neg = negative_prompt or LTX_NEGATIVE_PROMPT

        self.engine.generate_t2v(
            prompt=prompt,
            negative_prompt=neg,
            output_path=output_path,
            width=LTX_WIDTH,
            height=LTX_HEIGHT,
            num_frames=LTX_NUM_FRAMES,
            frame_rate=LTX_FRAME_RATE,
            num_inference_steps=LTX_INFERENCE_STEPS,
            seed=actual_seed,
        )

        print(f"[LTX] ✅ Clip generado: {output_path}")

        return VideoClip(
            file_path=output_path,
            duration=LTX_DURATION_SECONDS,
            seed=actual_seed,
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
        LTX-2 does not support native video extension.
        Falls back to jump_to_scene (extract last frame → generate new clip).
        """
        print("[LTX] ⚠️  extend_scene no soportado por LTX-2. Usando jump_to_scene.")
        return self.jump_to_scene(
            previous_clip=video_clip,
            prompt=prompt,
            save_dir=save_dir,
            scene_index=scene_index,
            narrative_phase=narrative_phase,
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
        Extracts last frame → passes as image conditioning to LTX-2.
        """
        print(f"[LTX] ⏭️  Jump To nueva escena: '{prompt[:60]}...'")

        # Extract last frame
        clips_dir = save_dir if save_dir else self.assets_dir
        frame_path = self.engine.extract_last_frame(
            previous_clip.file_path,
            output_image_path=os.path.join(clips_dir, f"last_frame_{(scene_index or 0) + 1:02d}.png"),
        )

        # Fallback: try saved PNG from previous scene
        if frame_path is None and save_dir and scene_index is not None and scene_index > 0:
            saved_frame = os.path.join(save_dir, f"last_frame_{scene_index:02d}.png")
            if os.path.exists(saved_frame):
                print(f"[LTX]    📷 Usando frame guardado: {os.path.basename(saved_frame)}")
                frame_path = saved_frame

        if frame_path is None:
            print("[LTX] ⚠️  No se pudo extraer frame. Generando sin seed visual.")
            return self.generate_scene(
                prompt, save_dir=save_dir, scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        # Build output path
        target_dir = save_dir if save_dir else self.assets_dir
        if scene_index is not None:
            filename = f"clip_{scene_index + 1:02d}.mp4"
        else:
            filename = f"jump_{int(time.time())}.mp4"
        output_path = os.path.join(target_dir, filename)

        # Generate image-to-video
        actual_seed = 42
        self.engine.generate_i2v(
            prompt=prompt,
            image_path=frame_path,
            negative_prompt=LTX_NEGATIVE_PROMPT,
            output_path=output_path,
            width=LTX_WIDTH,
            height=LTX_HEIGHT,
            num_frames=LTX_NUM_FRAMES,
            frame_rate=LTX_FRAME_RATE,
            num_inference_steps=LTX_INFERENCE_STEPS,
            seed=actual_seed,
        )

        print(f"[LTX] ✅ Jump clip generado: {output_path}")

        return VideoClip(
            file_path=output_path,
            duration=LTX_DURATION_SECONDS,
            seed=actual_seed,
        )

    # ==========================================
    # FULL VIDEO ORCHESTRATION (Scene Builder)
    # ==========================================

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
        Same resilient loop as VeoProvider.
        """
        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("El script no tiene escenas.")

        title = script.get("title", "Untitled")
        print(f"\n{'='*60}")
        print(f"[LTX] 🎬 Scene Builder — '{title}'")
        print(f"[LTX]    {len(scenes)} escenas a generar")
        if resume_from > 0:
            print(f"[LTX]    ▶️  Continuando desde escena {resume_from + 1}")
        print(f"{'='*60}\n")

        # Clip save directory
        if episode_dir:
            clips_dir = os.path.join(episode_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
        else:
            clips_dir = self.assets_dir

        # Collect clips — load previously generated if resuming
        clips: List[VideoClip] = []
        if resume_from > 0 and progress_manager:
            completed = progress_manager.get_completed_clips()
            for c in completed:
                if c.get("clip_path") and os.path.exists(c["clip_path"]):
                    clips.append(VideoClip(
                        file_path=c["clip_path"],
                        duration=c.get("duration_seconds", LTX_DURATION_SECONDS),
                    ))
            print(f"[LTX]    📂 {len(clips)} clips previos recuperados")

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)

            if i < resume_from:
                continue

            narrative_phase = scene.get("narrative_phase", "")
            prompt = self._build_cinematographic_prompt(scene, narrative_phase)
            negative = scene.get("negative_prompt")

            print(f"\n--- Escena {scene_num}/{len(scenes)} ---")

            try:
                if i == 0 or not clips:
                    clip = self.generate_scene(
                        prompt=prompt,
                        seed=scene.get("seed"),
                        negative_prompt=negative,
                        save_dir=clips_dir,
                        scene_index=i,
                        narrative_phase=narrative_phase,
                    )
                else:
                    clip = self.jump_to_scene(
                        previous_clip=clips[-1],
                        prompt=prompt,
                        save_dir=clips_dir,
                        scene_index=i,
                        narrative_phase=narrative_phase,
                    )

                clips.append(clip)
                print(f"[LTX] ✅ Escena {scene_num} generada: {clip.file_path}")

                # Save last frame for resume
                self.engine.extract_last_frame(
                    clip.file_path,
                    output_image_path=os.path.join(clips_dir, f"last_frame_{i + 1:02d}.png"),
                )

                # Persist progress
                if progress_manager:
                    progress_manager.mark_scene_completed(
                        scene_index=i,
                        clip_path=clip.file_path,
                        model_used="ltx-2-19b",
                    )

            except Exception as e:
                error_msg = str(e)
                print(f"[LTX] ❌ Error en escena {scene_num}: {error_msg[:120]}")
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
            if len(clips) >= len(scenes):
                progress_manager.mark_episode_completed(final_path)
            else:
                print(f"\n[LTX] ⏸️  Episodio parcial ({len(clips)}/{len(scenes)} clips). Resume con opción 4.")
                print(progress_manager.get_status_summary())

        status = "PARCIAL" if len(clips) < len(scenes) else "COMPLETO"
        print(f"\n{'='*60}")
        print(f"[LTX] ✅ Vídeo {status}: {final_path}")
        print(f"[LTX]    Clips generados: {len(clips)}/{len(scenes)}")
        print(f"{'='*60}\n")

        return final_path

    # ==========================================
    # HELPERS (same logic as VeoProvider)
    # ==========================================

    def _build_cinematographic_prompt(self, scene: dict, narrative_phase: str = "") -> str:
        """
        Build a detailed cinematographic prompt from scene metadata.
        Same structure as VeoProvider but LTX-2 handles audio natively
        via text in quotes, so we keep audio_text.
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

        # LTX-2 supports audio text in quotes natively
        audio_text = scene.get("audio_text", "")
        voice_direction = scene.get("voice_direction", "")
        if audio_text:
            voice_desc = f" ({voice_direction})" if voice_direction else ""
            parts.append(f'Character{voice_desc} says: "{audio_text}"')

        # Art style from config
        art_style = self.config.get("consistency", {}).get("art_style", "")
        if art_style:
            parts.append(art_style)

        final_prompt = ". ".join(filter(None, parts))
        # Safely truncate to 600 chars to avoid massive HF T5 tokenization warnings (>128 tokens)
        if len(final_prompt) > 600:
            final_prompt = final_prompt[:597] + "..."
            
        return final_prompt

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str) -> str:
        """Concatenate multiple video clips into one final video using ffmpeg."""
        try:
            concat_list_path = os.path.join(self.assets_dir, "_concat_list.txt")
            with open(concat_list_path, "w") as f:
                for clip in clips:
                    safe_path = clip.file_path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

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
                print(f"[LTX] ⚠️  ffmpeg error: {result.stderr[:200]}")
                return clips[0].file_path

            os.remove(concat_list_path)
            return output_path

        except FileNotFoundError:
            print("[LTX] ⚠️  ffmpeg no encontrado. Retornando primer clip.")
            return clips[0].file_path
