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


# TODO: [MIGRACIÓN] Este proveedor está acoplado actualmente a ltx_provider.py con dos JSONs locales.
# En el futuro, se debe migrar completamente la lógica de parseo al motor genérico usando 
# un archivo yaml en `providers.d/comfyui-ltx2` como se hizo con el resto de modelos (runway, veo, etc),
# de manera que se abstraiga la integración directa con ComfyUI.


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

        if reference_images and len(reference_images) > 0:
            log.info("ltx.reference_image_found", count=len(reference_images))
            ref_name = self._upload_image_to_comfyui(reference_images[0])
            if not ref_name:
                raise RuntimeError("[LTX] Failed to upload reference image to ComfyUI.")

            anchor_workflow = self._build_workflow_anchor(prompt, ref_name)
            log.info("ltx.starting_anchor_generation")
            anchor_image_path = self._submit_and_wait(anchor_workflow, save_dir, scene_index, prompt, stage="anchor")

            anchor_name = self._upload_image_to_comfyui(anchor_image_path)
            if not anchor_name:
                raise RuntimeError("[LTX] Failed to upload anchor image to ComfyUI.")

            workflow = self._build_workflow_i2v(
                prompt=prompt,
                negative_prompt=negative_prompt or "blurry, low quality, watermark, text, subtitles",
                frames=frames,
                seed=actual_seed,
                image_name=anchor_name,
            )
        else:
            workflow = self._build_workflow_t2v(
                prompt=prompt,
                negative_prompt=negative_prompt or "blurry, low quality, watermark, text, subtitles",
                frames=frames,
                seed=actual_seed,
            )

        # 1. Base Generation (19B)
        base_video_path = self._submit_and_wait(workflow, save_dir, scene_index, prompt, stage="base")

        # 2. Upload to ComfyUI for Upscaling
        log.info("ltx.uploading_for_upscale", path=base_video_path)
        input_video_name = self._upload_video_to_comfyui(base_video_path)
        if not input_video_name:
            raise RuntimeError("[LTX] Failed to upload base video to ComfyUI for upscaling.")

        # Pausa breve para asegurar que ComfyUI libera VRAM
        time.sleep(2)

        # 3. Upscale (4x-UltraSharp)
        log.info("ltx.starting_upscale", scene=scene_index)
        upscale_workflow = self._build_workflow_upscale(input_video_name)
        final_video_path = self._submit_and_wait(upscale_workflow, save_dir, scene_index, prompt, stage="upscaled")

        # Opcional: Borrar el video base local para no acumular basura
        try:
            if os.path.exists(base_video_path):
                os.remove(base_video_path)
        except Exception:
            pass

        return VideoClip(
            file_path=final_video_path,
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
        duration: int = 8,
        **kwargs: Any,
    ) -> VideoClip:
        """Jump to new scene using last frame of previous clip as image input."""
        log.info("ltx.jump_to_scene", prompt=prompt[:60])

        last_frame_path = self._get_last_frame_path(previous_clip.file_path, save_dir, scene_index)

        if last_frame_path is None:
            log.warning("ltx.no_last_frame_generating_t2v")
            return self.generate_scene(
                prompt=prompt,
                save_dir=save_dir,
                scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        frame_name = self._upload_image_to_comfyui(last_frame_path)
        if frame_name is None:
            log.warning("ltx.frame_upload_failed_generating_t2v")
            return self.generate_scene(
                prompt=prompt,
                save_dir=save_dir,
                scene_index=scene_index,
                narrative_phase=narrative_phase,
            )

        frames = self._duration_to_frames(duration)
        actual_seed = int(time.time() * 1000) % (2**32)

        workflow = self._build_workflow_i2v(
            prompt=prompt,
            negative_prompt="blurry, low quality, watermark, text, subtitles",
            frames=frames,
            seed=actual_seed,
            image_name=frame_name,
        )

        base_video_path = self._submit_and_wait(workflow, save_dir, scene_index, prompt, stage="base")

        log.info("ltx.uploading_for_upscale", path=base_video_path)
        input_video_name = self._upload_video_to_comfyui(base_video_path)
        if not input_video_name:
            raise RuntimeError("[LTX] Failed to upload base video to ComfyUI for upscaling.")

        time.sleep(2)

        log.info("ltx.starting_upscale", scene=scene_index)
        upscale_workflow = self._build_workflow_upscale(input_video_name)
        final_video_path = self._submit_and_wait(upscale_workflow, save_dir, scene_index, prompt, stage="upscaled")

        try:
            if os.path.exists(base_video_path):
                os.remove(base_video_path)
        except Exception:
            pass

        return VideoClip(
            file_path=final_video_path,
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

    def _build_workflow_anchor(
        self,
        prompt: str,
        image_name: str,
    ) -> dict:
        import json
        import os
        
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "providers.d", "comfyui-ltx2", "api_anchor_workflow.json")
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
            
        workflow["6"]["inputs"]["text"] = prompt
        workflow["12"]["inputs"]["image"] = image_name
        
        return workflow

    def _build_workflow_t2v(
        self,
        prompt: str,
        negative_prompt: str,
        frames: int,
        seed: int,
    ) -> dict:
        import json
        import os
        
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "providers.d", "comfyui-ltx2", "api_workflow.json")
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
            
        # Inject our values into the nodes we identified
        # Prompt node
        workflow["5222"]["inputs"]["value"] = prompt
        
        # Seed node
        workflow["5232:5158"]["inputs"]["noise_seed"] = seed
        
        # Frames
        workflow["5218"]["inputs"]["value"] = frames
        
        return workflow

    def _build_workflow_i2v(
        self,
        prompt: str,
        negative_prompt: str,
        frames: int,
        seed: int,
        image_name: str,
    ) -> dict:
        import json
        import os
        
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "providers.d", "comfyui-ltx2", "api_i2v_workflow.json")
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
            
        workflow["5222"]["inputs"]["value"] = prompt
        workflow["5232:5158"]["inputs"]["noise_seed"] = seed
        workflow["5218"]["inputs"]["value"] = frames
        workflow["load_image"]["inputs"]["image"] = image_name
        
        return workflow

    def _build_workflow_upscale(
        self,
        video_name: str,
    ) -> dict:
        import json
        import os
        
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "providers.d", "comfyui-ltx2", "api_upscale_workflow.json")
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
            
        for node_id, node in workflow.items():
            if node.get("class_type") == "VHS_LoadVideo":
                node["inputs"]["video"] = video_name
            elif node.get("class_type") == "VHS_VideoCombine":
                node["inputs"]["frame_rate"] = LTX_FPS
                
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
        stage: str = "base"
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
            log.info("ltx.prompt_submitted", prompt_id=prompt_id[:12], stage=stage)

            # Poll for completion
            elapsed = 0
            while elapsed < LTX_TIMEOUT:
                time.sleep(5)
                elapsed += 5
                
                # Emit progress ETA
                cb = getattr(self, "progress_callback", None)
                if cb:
                    total_s = 300.0 if stage == "base" else (45.0 if stage == "anchor" else 240.0)
                    pct_stage = min(elapsed / total_s, 0.95)
                    
                    if stage == "anchor":
                        pct_scene = pct_stage * 0.1
                    elif stage == "base":
                        pct_scene = 0.1 + pct_stage * 0.5
                    else:
                        pct_scene = 0.6 + pct_stage * 0.4
                        
                    scene_idx = getattr(self, "_current_scene_index", 0)
                    total = getattr(self, "_total_scenes", 1)
                    total = max(1, total)
                    overall_pct = (scene_idx + pct_scene) / total
                    
                    eta = max(10, int(total_s - elapsed))
                    stage_label = "Imagen Ancla" if stage == "anchor" else ("Clip Base" if stage == "base" else "Escalado")
                    msg = f"Escena {scene_idx+1}/{total} [{stage_label}] - ETA ~{eta}s"
                    cb(overall_pct, msg)
                else:
                    if elapsed % 30 == 0:
                        eta = 300 - elapsed if stage == "base" else 240 - elapsed
                        eta = max(10, eta)
                        log.info(f"ltx.polling_{stage}", elapsed_s=elapsed, estimated_eta_s=eta)

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
                            save_dir, scene_index, prompt, stage
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

    def _upload_video_to_comfyui(self, video_path: str) -> Optional[str]:
        """Upload a video to ComfyUI's input folder for processing."""
        try:
            filename = os.path.basename(video_path)
            with open(video_path, "rb") as f:
                response = httpx.post(
                    f"{self.comfyui_url}/upload/image",
                    files={"image": (filename, f, "video/mp4")},
                    data={"overwrite": "true", "type": "input"},
                    timeout=60,
                )
            if response.status_code == 200:
                result = response.json()
                return result.get("name", filename)
            else:
                log.warning("ltx.video_upload_failed", status=response.status_code)
                return None
        except Exception as e:
            log.warning("ltx.video_upload_error", error=str(e))
            return None

    def _download_output(
        self,
        filename: str,
        subfolder: str,
        file_type: str,
        save_dir: Optional[str],
        scene_index: Optional[int],
        prompt: str,
        stage: str = "base"
    ) -> str:
        """Download a generated video from ComfyUI's output."""
        url = f"{self.comfyui_url}/view"
        params = {"filename": filename, "subfolder": subfolder, "type": file_type}

        response = httpx.get(url, params=params, timeout=60)

        # Build output filename
        ext = ".png" if stage == "anchor" else ".mp4"
        if scene_index is not None:
            if stage == "base":
                out_filename = f"clip_{scene_index + 1:02d}_base{ext}"
            elif stage == "anchor":
                out_filename = f"clip_{scene_index + 1:02d}_anchor{ext}"
            else:
                out_filename = f"clip_{scene_index + 1:02d}{ext}"
        else:
            out_filename = f"ltx_{int(time.time())}_{stage}{ext}"

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

