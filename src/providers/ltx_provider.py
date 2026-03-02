"""
LtxProvider — Local video generation via ComfyUI with LTX-2.

Generates video locally on your GPU without consuming cloud API tokens.
Uses ComfyUI as the inference backend with LTX-2 model (19B params, FP4).

LTX-2 generates audio natively (music, sound effects, dialogue) using Gemma 3
as its text encoder. Audio is produced in the same generation pass.

Requires:
- ComfyUI running locally at LTX_COMFYUI_URL (default: http://127.0.0.1:8188)
- LTX-2 checkpoint + distilled LoRA installed in ComfyUI
- Gemma 3 text encoder in ComfyUI/models/text_encoders/
- NVIDIA GPU with 12GB+ VRAM
"""

import os
import json
import time
import subprocess
import uuid
import cv2
import httpx
from typing import Optional, List, Dict, Any

from src.providers.base_provider import BaseVideoProvider, VideoClip
from src.variables import (
    LTX_COMFYUI_URL,
    LTX_CHECKPOINT,
    LTX_LORA,
    LTX_LORA_STRENGTH,
    LTX_TEXT_ENCODER,
    LTX_WIDTH,
    LTX_HEIGHT,
    LTX_FPS,
    LTX_STEPS,
    LTX_CFG,
    LTX_DENOISE,
    LTX_TIMEOUT,
)


class LtxProvider(BaseVideoProvider):
    """Local video generation via ComfyUI with LTX-2."""

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        self.comfyui_url = LTX_COMFYUI_URL

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_availability(self) -> bool:
        """Check if ComfyUI is running and accessible."""
        try:
            response = httpx.get(f"{self.comfyui_url}/system_stats", timeout=5)
            if response.status_code == 200:
                stats = response.json()
                devices = stats.get("devices", [{}])
                if devices:
                    vram = devices[0].get("vram_total", 0)
                    vram_gb = vram / (1024**3) if vram else 0
                    print(f"[LTX] ✅ ComfyUI disponible en {self.comfyui_url}")
                    print(f"[LTX]    VRAM: {vram_gb:.1f} GB")
                    print(f"[LTX]    Modelo: {LTX_CHECKPOINT}")
                    print(f"[LTX]    LoRA: {LTX_LORA}")
                else:
                    print(f"[LTX] ✅ ComfyUI disponible en {self.comfyui_url}")
                return True
            return False
        except Exception as e:
            print(f"[LTX] ❌ ComfyUI no disponible en {self.comfyui_url}")
            print(f"[LTX]    Error: {e}")
            print(f"[LTX]    Asegúrate de que ComfyUI está corriendo.")
            return False

    # ==========================================
    # SCENE GENERATION METHODS
    # ==========================================

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
        """Generate a video scene via ComfyUI text-to-video workflow."""
        print(f"[LTX] 🎬 Generando escena (T2V): '{prompt[:60]}...'")

        # Calculate frame count from duration
        frames = self._duration_to_frames(duration)
        actual_seed = seed or int(time.time() * 1000) % (2**32)

        workflow = self._build_workflow_t2v(
            prompt=prompt,
            negative_prompt=negative_prompt or "blurry, low quality, watermark, text, subtitles",
            frames=frames,
            seed=actual_seed,
        )

        output_path = self._submit_and_wait(workflow, save_dir, scene_index, prompt)

        return VideoClip(
            file_path=output_path,
            duration=duration,
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
        """Extend scene — disabled. Falls back to jump_to_scene."""
        print(f"[LTX] 🔄 Extend deshabilitado. Usando jump_to_scene.")
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
        """Jump to new scene using last frame of previous clip as image input."""
        print(f"[LTX] ⏭️  Jump To (I2V): '{prompt[:60]}...'")

        # Extract last frame from previous clip
        last_frame_path = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)

        if last_frame_path is None:
            print("[LTX] ⚠️  No se pudo extraer último frame. Generando T2V sin seed visual.")
            return self.generate_scene(
                prompt=prompt,
                save_dir=save_dir,
                scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        # Upload the frame to ComfyUI's input folder
        frame_name = self._upload_image_to_comfyui(last_frame_path)
        if frame_name is None:
            print("[LTX] ⚠️  No se pudo subir frame a ComfyUI. Generando T2V.")
            return self.generate_scene(
                prompt=prompt,
                save_dir=save_dir,
                scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        frames = self._duration_to_frames(8)  # I2V default duration
        actual_seed = int(time.time() * 1000) % (2**32)

        workflow = self._build_workflow_i2v(
            prompt=prompt,
            negative_prompt="blurry, low quality, watermark, text, subtitles",
            frames=frames,
            seed=actual_seed,
            image_name=frame_name,
        )

        output_path = self._submit_and_wait(workflow, save_dir, scene_index, prompt)

        return VideoClip(
            file_path=output_path,
            duration=8,
            seed=actual_seed,
        )

    # ==========================================
    # FULL VIDEO PIPELINE (mirrors VeoProvider)
    # ==========================================

    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
        episode_dir: str = None,
        resume_from: int = 0,
        progress_manager=None,
    ) -> str:
        """Generate full video — same loop structure as VeoProvider."""
        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("El script no tiene escenas.")

        title = script.get("title", "Untitled")
        print(f"\n{'='*60}")
        print(f"[LTX] 🎬 Scene Builder Local — '{title}'")
        print(f"[LTX]    {len(scenes)} escenas | GPU: Local ({LTX_CHECKPOINT})")
        if resume_from > 0:
            print(f"[LTX]    ▶️  Continuando desde escena {resume_from + 1}")
        print(f"{'='*60}\n")

        # Determine clip save directory
        if episode_dir:
            clips_dir = os.path.join(episode_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
        else:
            clips_dir = self.assets_dir

        # Load previously generated clips if resuming
        clips: List[VideoClip] = []
        if resume_from > 0 and progress_manager:
            completed = progress_manager.get_completed_clips()
            for c in completed:
                if c.get("clip_path") and os.path.exists(c["clip_path"]):
                    clips.append(VideoClip(
                        file_path=c["clip_path"],
                        duration=c.get("duration_seconds", 8),
                    ))
            print(f"[LTX]    📂 {len(clips)} clips previos recuperados")

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)

            # Skip already completed scenes
            if i < resume_from:
                continue

            narrative_phase = scene.get("narrative_phase", "")
            prompt = self._build_cinematographic_prompt(scene, narrative_phase)
            negative = scene.get("negative_prompt")
            scene_duration = scene.get("duration_seconds", 8)
            scene_duration = max(4, min(scene_duration, 8))

            print(f"\n--- Escena {scene_num}/{len(scenes)} ({scene_duration}s) ---")

            try:
                if i == 0 or not clips:
                    clip = self.generate_scene(
                        prompt=prompt,
                        duration=scene_duration,
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

                # Save last frame for resume safety
                self._save_last_frame(clip.file_path, clips_dir, i)

                # Persist progress
                if progress_manager:
                    progress_manager.mark_scene_completed(
                        scene_index=i,
                        clip_path=clip.file_path,
                        model_used=LTX_CHECKPOINT,
                    )

            except Exception as e:
                error_msg = str(e)
                print(f"[LTX] ❌ Error en escena {scene_num}: {error_msg[:120]}")
                print(f"[LTX] 🛑 Guardando progreso y parando.")
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

        completed_count = len(clips)
        total_count = len(scenes)
        status = "PARCIAL" if completed_count < total_count else "COMPLETO"

        print(f"\n{'='*60}")
        print(f"[LTX] {'⏸️' if completed_count < total_count else '✅'} Vídeo {status}: {final_path}")
        print(f"[LTX]    Clips generados: {completed_count}/{total_count}")
        print(f"{'='*60}\n")

        return final_path

    # ==========================================
    # COMFYUI WORKFLOW BUILDERS
    # ==========================================

    def _build_workflow_t2v(
        self,
        prompt: str,
        negative_prompt: str,
        frames: int,
        seed: int,
    ) -> dict:
        """Build ComfyUI API-format workflow for LTX-2 text-to-video."""
        return {
            # 1. Load checkpoint
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": LTX_CHECKPOINT},
            },
            # 2. Load Gemma text encoder
            "2": {
                "class_type": "LTXVGemmaCLIPModelLoader",
                "inputs": {
                    "clip_name": LTX_TEXT_ENCODER,
                    "ckpt_name": LTX_CHECKPOINT,
                    "max_seq_len": 1024,
                },
            },
            # 3. Load distilled LoRA
            "3": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["1", 0],
                    "lora_name": LTX_LORA,
                    "strength_model": LTX_LORA_STRENGTH,
                },
            },
            # 4. Positive prompt encoding
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["2", 0],
                },
            },
            # 5. Negative prompt encoding
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["2", 0],
                },
            },
            # 6. LTX-2 conditioning
            "6": {
                "class_type": "LTXVConditioning",
                "inputs": {
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "frame_rate": LTX_FPS,
                },
            },
            # 7. Empty latent video
            "7": {
                "class_type": "EmptyLTXVLatentVideo",
                "inputs": {
                    "width": LTX_WIDTH,
                    "height": LTX_HEIGHT,
                    "length": frames,
                    "batch_size": 1,
                },
            },
            # 8. KSampler
            "8": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": LTX_STEPS,
                    "cfg": LTX_CFG,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": LTX_DENOISE,
                    "model": ["3", 0],
                    "positive": ["6", 0],
                    "negative": ["6", 1],
                    "latent_image": ["7", 0],
                },
            },
            # 9. VAE Decode
            "9": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["8", 0],
                    "vae": ["1", 2],
                },
            },
            # 10. Audio VAE loader (loads the audio decoder weights)
            "10": {
                "class_type": "LTXVAudioVAELoader",
                "inputs": {
                    "ckpt_name": LTX_CHECKPOINT,
                },
            },
            # 11. Decode audio from sampled latents using audio VAE
            "11": {
                "class_type": "LTXVAudioVAEDecode",
                "inputs": {
                    "samples": ["8", 0],
                    "audio_vae": ["10", 0],
                },
            },
            # 12. Create video from frames + decoded audio
            "12": {
                "class_type": "CreateVideo",
                "inputs": {
                    "images": ["9", 0],
                    "fps": float(LTX_FPS),
                    "audio": ["11", 0],
                },
            },
            # 13. Save video to disk
            "13": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["12", 0],
                    "filename_prefix": f"ltx_t2v_{seed}",
                    "format": "auto",
                    "codec": "auto",
                },
            },
        }

    def _build_workflow_i2v(
        self,
        prompt: str,
        negative_prompt: str,
        frames: int,
        seed: int,
        image_name: str,
    ) -> dict:
        """Build ComfyUI API-format workflow for LTX-2 image-to-video."""
        workflow = self._build_workflow_t2v(prompt, negative_prompt, frames, seed)

        # Add LoadImage node (use IDs 20+ to avoid conflicts with T2V nodes)
        workflow["20"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name, "upload": "image"},
        }

        # Encode image as latent
        workflow["21"] = {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["20", 0],
                "vae": ["1", 2],
            },
        }

        # Update KSampler to use encoded image as latent
        workflow["8"]["inputs"]["latent_image"] = ["21", 0]
        # Lower denoise for I2V (preserve more of the input image structure)
        workflow["8"]["inputs"]["denoise"] = 0.85

        # Update filename prefix (node 13 = SaveVideo)
        workflow["13"]["inputs"]["filename_prefix"] = f"ltx_i2v_{seed}"
        # Remove empty latent node (not needed for I2V)
        del workflow["7"]

        return workflow

    # ==========================================
    # COMFYUI API INTERACTION
    # ==========================================

    def _submit_and_wait(
        self,
        workflow: dict,
        save_dir: Optional[str],
        scene_index: Optional[int],
        prompt: str,
    ) -> str:
        """Submit workflow to ComfyUI and wait for results."""
        client_id = str(uuid.uuid4())

        try:
            response = httpx.post(
                f"{self.comfyui_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
                timeout=10,
            )

            if response.status_code != 200:
                raise Exception(f"ComfyUI error: {response.status_code} - {response.text}")

            prompt_id = response.json().get("prompt_id")
            print(f"[LTX] ⏳ Prompt enviado: {prompt_id[:12]}...")

            # Poll for completion
            elapsed = 0
            while elapsed < LTX_TIMEOUT:
                time.sleep(5)
                elapsed += 5
                if elapsed % 30 == 0:
                    print(f"[LTX] ⏳ Esperando... ({elapsed}s)")

                history = httpx.get(
                    f"{self.comfyui_url}/history/{prompt_id}",
                    timeout=10,
                ).json()

                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    # Find the output node with videos/gifs
                    for node_id, output in outputs.items():
                        items = output.get("videos", output.get("gifs", output.get("images", [])))
                        if items:
                            filename = items[0]["filename"]
                            subfolder = items[0].get("subfolder", "")
                            file_type = items[0].get("type", "output")
                            return self._download_output(
                                filename, subfolder, file_type,
                                save_dir, scene_index, prompt,
                            )

                    # Check for errors
                    status = history[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(f"ComfyUI error: {msgs}")
                    break

            raise TimeoutError(f"[LTX] Timeout ({LTX_TIMEOUT}s) esperando generación.")

        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ConnectionError(
                f"[LTX] No se pudo conectar a ComfyUI en {self.comfyui_url}. "
                f"¿Está corriendo?"
            )

    def _upload_image_to_comfyui(self, image_path: str) -> Optional[str]:
        """Upload an image to ComfyUI's input folder."""
        try:
            filename = os.path.basename(image_path)
            with open(image_path, "rb") as f:
                response = httpx.post(
                    f"{self.comfyui_url}/upload/image",
                    files={"image": (filename, f, "image/png")},
                    data={"overwrite": "true"},
                    timeout=10,
                )
            if response.status_code == 200:
                result = response.json()
                return result.get("name", filename)
            else:
                print(f"[LTX] ⚠️  Error subiendo imagen: {response.status_code}")
                return None
        except Exception as e:
            print(f"[LTX] ⚠️  Error subiendo imagen: {e}")
            return None

    def _download_output(
        self,
        filename: str,
        subfolder: str,
        file_type: str,
        save_dir: Optional[str],
        scene_index: Optional[int],
        prompt: str,
    ) -> str:
        """Download a generated video from ComfyUI's output."""
        url = f"{self.comfyui_url}/view"
        params = {"filename": filename, "subfolder": subfolder, "type": file_type}

        response = httpx.get(url, params=params, timeout=60)

        # Build output filename
        if scene_index is not None:
            out_filename = f"clip_{scene_index + 1:02d}.mp4"
        else:
            out_filename = f"ltx_{int(time.time())}.mp4"

        target_dir = save_dir if save_dir else self.assets_dir
        output_path = os.path.join(target_dir, out_filename)

        with open(output_path, "wb") as f:
            f.write(response.content)

        print(f"[LTX] 💾 Descargado: {output_path}")
        return output_path

    # ==========================================
    # FRAME EXTRACTION (same as VeoProvider)
    # ==========================================

    def _get_last_frame_path(
        self,
        video_path: str,
        save_dir: Optional[str],
        scene_index: Optional[int],
    ) -> Optional[str]:
        """Get the last frame: try extracting from video, fallback to saved PNG."""
        # Try saved PNG first (faster, more reliable)
        if save_dir and scene_index is not None and scene_index > 0:
            saved_frame = os.path.join(save_dir, f"last_frame_{scene_index:02d}.png")
            if os.path.exists(saved_frame):
                print(f"[LTX]    📷 Usando frame guardado: {os.path.basename(saved_frame)}")
                return saved_frame

        # Extract from video
        try:
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
            ret, frame = cap.read()
            cap.release()
            if ret:
                temp_path = os.path.join(
                    save_dir or self.assets_dir,
                    f"_temp_lastframe.png"
                )
                cv2.imwrite(temp_path, frame)
                return temp_path
        except Exception as e:
            print(f"[LTX] ⚠️  Error extrayendo frame: {e}")

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
                print(f"[LTX]    📷 Último frame guardado: {os.path.basename(frame_path)}")
        except Exception as e:
            print(f"[LTX] ⚠️  No se pudo guardar último frame: {e}")

    # ==========================================
    # PROMPT BUILDER (mirrors VeoProvider)
    # ==========================================

    def _build_cinematographic_prompt(self, scene: dict, narrative_phase: str = "") -> str:
        """Build a detailed cinematographic prompt from scene data."""
        parts = []

        # Camera settings
        camera = scene.get("camera", {})
        shot = camera.get("shot_type", "")
        movement = camera.get("movement", "static")
        angle = camera.get("angle", "eye_level")
        if shot:
            parts.append(f"{shot} shot. camera {movement}. {angle} angle.")

        # Mood and lighting
        mood = scene.get("mood", "")
        lighting = scene.get("lighting", "")
        if mood:
            parts.append(f"{mood} mood.")
        if lighting:
            parts.append(f"{lighting}.")

        # Visual prompt (the core description)
        visual = scene.get("visual_prompt", "")
        if visual:
            parts.append(visual)

        # Audio/dialogue — LTX-2 supports audio natively
        audio_text = scene.get("audio_text", "")
        character = scene.get("character", "")
        voice_direction = scene.get("voice_direction", "")

        if audio_text:
            voice_desc = f" ({voice_direction})" if voice_direction else " (young cheerful male voice, European Spanish)"
            parts.append(f'{character}{voice_desc} says: "{audio_text}"')

        # Art style from config
        art_style = self.config.get("consistency", {}).get("art_style", "")
        if art_style:
            parts.append(f"Style: {art_style}")

        return " ".join(parts)

    # ==========================================
    # UTILITIES
    # ==========================================

    def _duration_to_frames(self, duration_seconds: int) -> int:
        """Convert duration in seconds to frame count for LTX-2.
        LTX-2 frame count must be divisible by 8 + 1 (e.g., 97, 121, 193, 241)."""
        raw_frames = duration_seconds * LTX_FPS
        # Round to nearest valid LTX-2 frame count (8n + 1)
        n = round((raw_frames - 1) / 8)
        return max(8 * n + 1, 25)  # minimum 25 frames (~1 second)

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str) -> str:
        """Concatenate clips using ffmpeg."""
        try:
            concat_list = os.path.join(self.assets_dir, "_concat_list.txt")
            with open(concat_list, "w") as f:
                for clip in clips:
                    safe_path = clip.file_path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", output_path],
                capture_output=True, text=True,
            )
            os.remove(concat_list)
            return output_path
        except FileNotFoundError:
            print("[LTX] ⚠️  ffmpeg no encontrado. Devolviendo primer clip.")
            return clips[0].file_path
