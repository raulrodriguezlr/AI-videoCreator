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

import structlog
from videocreator.infrastructure.engine.providers.base_provider import BaseVideoProvider, VideoClip
from videocreator.infrastructure.engine.variables import (
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

log = structlog.get_logger(__name__)


class LtxProvider(BaseVideoProvider):
    """Local video generation via ComfyUI with LTX-2."""

    LOG_TAG = "[LTX]"

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        self.comfyui_url = LTX_COMFYUI_URL
        # Resolve actual text encoder path from ComfyUI (OS-agnostic)
        self._resolved_text_encoder = self._resolve_text_encoder_path()

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _resolve_text_encoder_path(self) -> str:
        """Query ComfyUI to get the correct text encoder path (OS-agnostic).

        ComfyUI returns paths with the native OS separator (backslash on Windows,
        forward slash on Linux/Docker). We match by folder name to find the right one.
        """
        try:
            r = httpx.get(
                f"{self.comfyui_url}/object_info/LTXVGemmaCLIPModelLoader",
                timeout=5,
            )
            if r.status_code == 200:
                info = r.json()
                node = info.get("LTXVGemmaCLIPModelLoader", {})
                options = (
                    node.get("input", {})
                    .get("required", {})
                    .get("gemma_path", [[]])[0]
                )
                # Match by folder name from LTX_TEXT_ENCODER
                folder = LTX_TEXT_ENCODER.replace("\\", "/").split("/")[0]
                for opt in options:
                    if folder in opt:
                        log.info("ltx.text_encoder_resolved", path=opt)
                        return opt
        except Exception:
            pass

        # Fallback to configured value
        log.warning("ltx.text_encoder_fallback", path=LTX_TEXT_ENCODER)
        return LTX_TEXT_ENCODER

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
                    log.info("ltx.comfyui_ready", url=self.comfyui_url, vram_gb=round(vram_gb, 1), model=LTX_CHECKPOINT, lora=LTX_LORA)
                else:
                    log.info("ltx.comfyui_ready", url=self.comfyui_url)
                return True
            return False
        except Exception as e:
            log.error("ltx.comfyui_unavailable", url=self.comfyui_url, error=str(e))
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
        log.info("ltx.generate_scene", prompt=prompt[:60])

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
        log.info("ltx.extend_disabled_using_jump")
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
        log.info("ltx.jump_to_scene", prompt=prompt[:60])

        # Extract last frame from previous clip
        last_frame_path = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)

        if last_frame_path is None:
            log.warning("ltx.no_last_frame_generating_t2v")
            return self.generate_scene(
                prompt=prompt,
                save_dir=save_dir,
                scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        # Upload the frame to ComfyUI's input folder
        frame_name = self._upload_image_to_comfyui(last_frame_path)
        if frame_name is None:
            log.warning("ltx.frame_upload_failed_generating_t2v")
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
    # SCENE-BUILDER HOOKS (the shared loop lives in BaseVideoProvider)
    # ==========================================
    def _model_label(self) -> str:
        return LTX_CHECKPOINT

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
        """Build ComfyUI API-format workflow for LTX-2 text-to-video.

        Uses LowVRAM loaders for 12GB GPU compatibility.
        FP4 checkpoint does NOT embed Gemma, so we load it separately.
        """
        return {
            # 1. Load checkpoint MODEL + VAE
            # ComfyUI handles VRAM offloading to CPU automatically
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": LTX_CHECKPOINT},
            },
            # 2. Load Gemma text encoder separately (CLIP)
            "2": {
                "class_type": "LTXVGemmaCLIPModelLoader",
                "inputs": {
                    "gemma_path": self._resolved_text_encoder,
                    "ltxv_path": LTX_CHECKPOINT,
                    "max_length": 1024,
                },
            },
            # 3. Load distilled LoRA (on MODEL from node 1)
            "3": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["1", 0],
                    "lora_name": LTX_LORA,
                    "strength_model": LTX_LORA_STRENGTH,
                },
            },
            # 4. Positive prompt encoding (CLIP from Gemma, node 2)
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
            # 8. KSampler (MODEL from LoRA node 3)
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
            # 9. VAE Decode (VAE from checkpoint node 1, output 2)
            "9": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["8", 0],
                    "vae": ["1", 2],
                },
            },
            # 10. Audio VAE loader
            "10": {
                "class_type": "LTXVAudioVAELoader",
                "inputs": {
                    "ckpt_name": LTX_CHECKPOINT,
                },
            },
            # 11. Decode audio from sampled latents
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

        # Update KSampler to use encoded image as latent (node 8 = KSampler)
        workflow["8"]["inputs"]["latent_image"] = ["21", 0]
        # Lower denoise for I2V (preserve more of the input image structure)
        workflow["8"]["inputs"]["denoise"] = 0.85

        # Update filename prefix (node 13 = SaveVideo)
        workflow["13"]["inputs"]["filename_prefix"] = f"ltx_i2v_{seed}"
        # Remove empty latent node (not needed for I2V, node 7 = EmptyLTXVLatentVideo)
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
                error_detail = response.text[:500]
                raise Exception(f"ComfyUI error: {response.status_code} - {error_detail}")

            prompt_id = response.json().get("prompt_id")
            log.info("ltx.prompt_submitted", prompt_id=prompt_id[:12])

            # Poll for completion
            elapsed = 0
            while elapsed < LTX_TIMEOUT:
                time.sleep(5)
                elapsed += 5
                if elapsed % 30 == 0:
                    log.info("ltx.polling", elapsed_s=elapsed)

                history = httpx.get(
                    f"{self.comfyui_url}/history/{prompt_id}",
                    timeout=10,
                ).json()

                if prompt_id not in history:
                    continue  # Not in history yet, keep waiting

                entry = history[prompt_id]
                status = entry.get("status", {})
                status_str = status.get("status_str", "")

                # Still running — keep polling
                if status_str not in ("success", "error"):
                    continue

                # Execution error — extract full details
                if status_str == "error":
                    msgs = status.get("messages", [])
                    error_detail = "Ejecución fallida en ComfyUI"
                    for msg in msgs:
                        if isinstance(msg, list) and len(msg) >= 2:
                            msg_type = msg[0]
                            msg_data = msg[1] if isinstance(msg[1], dict) else {}
                            if msg_type == "execution_error":
                                node_type = msg_data.get("node_type", "?")
                                node_id = msg_data.get("node_id", "?")
                                exception_msg = msg_data.get("exception_message", "")
                                traceback_lines = msg_data.get("traceback", [])
                                error_detail = (
                                    f"Nodo '{node_type}' (ID {node_id}): {exception_msg}"
                                )
                                if traceback_lines:
                                    tb = "\n".join(traceback_lines[-3:])
                                    log.error("ltx.comfyui_traceback", traceback=tb)
                    raise RuntimeError(f"[LTX] {error_detail}")

                # Success — find the output video
                outputs = entry.get("outputs", {})
                for node_id, output in outputs.items():
                    items = (
                        output.get("videos", [])
                        or output.get("gifs", [])
                        or output.get("images", [])
                    )
                    if items:
                        filename = items[0]["filename"]
                        subfolder = items[0].get("subfolder", "")
                        file_type = items[0].get("type", "output")
                        return self._download_output(
                            filename, subfolder, file_type,
                            save_dir, scene_index, prompt,
                        )

                raise RuntimeError(
                    "[LTX] ComfyUI terminó pero no generó ningún archivo de salida."
                )

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
                log.warning("ltx.image_upload_failed", status=response.status_code)
                return None
        except Exception as e:
            log.warning("ltx.image_upload_error", error=str(e))
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

        log.info("ltx.clip_downloaded", path=output_path)
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
            frames_dir = os.path.join(os.path.dirname(save_dir), "frames")
            saved_frame = os.path.join(frames_dir, f"last_frame_{scene_index:02d}.png")
            if os.path.exists(saved_frame):
                log.info("ltx.using_saved_frame", frame=os.path.basename(saved_frame))
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
            log.warning("ltx.frame_extraction_error", error=str(e))

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
                log.info("ltx.last_frame_saved", frame=os.path.basename(frame_path))
        except Exception as e:
            log.warning("ltx.last_frame_save_failed", error=str(e))

    # ==========================================
    # PROMPT BUILDER (mirrors VeoProvider)
    # ==========================================

    def _duration_to_frames(self, duration_seconds: int) -> int:
        """Convert duration in seconds to frame count for LTX-2.
        LTX-2 frame count must be divisible by 8 + 1 (e.g., 97, 121, 193, 241)."""
        raw_frames = duration_seconds * LTX_FPS
        # Round to nearest valid LTX-2 frame count (8n + 1)
        n = round((raw_frames - 1) / 8)
        return max(8 * n + 1, 25)  # minimum 25 frames (~1 second)

