"""
OviProvider — Local video generation via ComfyUI API.

This is the TESTING/DEV provider. Generates video locally on your GPU
without consuming cloud API tokens. Uses ComfyUI as the inference backend
with Ovi or LTX-2 models quantized to FP4 for 12GB VRAM GPUs.

Requires:
- ComfyUI running locally at OVI_COMFYUI_URL (default: http://127.0.0.1:8188)
- Ovi/LTX-2 model installed in ComfyUI
- NVIDIA GPU with 12GB+ VRAM (RTX 4070 Ti or similar)

Setup guide: See README.md section "Configuración de Ovi (Local)"
"""

import os
import json
import time
import httpx
from typing import Optional, List, Dict, Any

from src.providers.base_provider import BaseVideoProvider, VideoClip
from src.variables import (
    OVI_COMFYUI_URL,
    OVI_QUANTIZATION,
    OVI_RESOLUTION,
    OVI_TIMEOUT,
)


class OviProvider(BaseVideoProvider):
    """Local video generation via ComfyUI with Ovi/LTX-2."""

    def __init__(self, pod_config_path: str):
        super().__init__(pod_config_path)
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        self.assets_dir = os.path.join(self.pod_dir, "assets")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)
        self.comfyui_url = OVI_COMFYUI_URL

    def _load_config(self, path: str) -> dict:
        """Load pod configuration from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_availability(self) -> bool:
        """Check if ComfyUI is running and accessible."""
        try:
            response = httpx.get(f"{self.comfyui_url}/system_stats", timeout=5)
            if response.status_code == 200:
                stats = response.json()
                vram = stats.get("devices", [{}])[0].get("vram_total", 0)
                vram_gb = vram / (1024**3) if vram else 0
                print(f"[OVI] ✅ ComfyUI disponible en {self.comfyui_url}")
                print(f"[OVI]    VRAM: {vram_gb:.1f} GB | Cuantización: {OVI_QUANTIZATION}")
                return True
            return False
        except Exception as e:
            print(f"[OVI] ❌ ComfyUI no disponible en {self.comfyui_url}")
            print(f"[OVI]    Error: {e}")
            print(f"[OVI]    Asegúrate de que ComfyUI está corriendo.")
            print(f"[OVI]    Guía: ver README.md sección 'Configuración Ovi (Local)'")
            return False

    def generate_scene(
        self,
        prompt: str,
        duration: int = 5,
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        negative_prompt: Optional[str] = None,
    ) -> VideoClip:
        """Generate a video scene via ComfyUI workflow."""
        print(f"[OVI] 🎬 Generando escena local: '{prompt[:60]}...'")
        print(f"[OVI]    Resolución: {OVI_RESOLUTION} | Cuantización: {OVI_QUANTIZATION}")

        # Build ComfyUI workflow
        workflow = self._build_workflow(
            prompt=prompt,
            seed=seed or int(time.time()),
            negative_prompt=negative_prompt or "",
        )

        # Submit to ComfyUI
        output_path = self._submit_and_wait(workflow, prompt)
        
        return VideoClip(
            file_path=output_path,
            duration=duration,
            seed=seed,
        )

    def extend_scene(
        self,
        video_clip: VideoClip,
        prompt: str,
    ) -> VideoClip:
        """
        Extend scene locally. Note: Ovi's extend capabilities are limited
        compared to Veo. Falls back to generating a new scene with similar prompt.
        """
        print(f"[OVI] 🔄 Extend no soportado nativamente en local. Generando nueva escena.")
        return self.generate_scene(prompt=prompt, seed=video_clip.seed)

    def jump_to_scene(
        self,
        previous_clip: VideoClip,
        prompt: str,
        reference_images: Optional[List[str]] = None,
    ) -> VideoClip:
        """
        Jump to new scene. Generates independently (no frame seeding in local mode).
        """
        print(f"[OVI] ⏭️  Jump To (local): '{prompt[:60]}...'")
        return self.generate_scene(prompt=prompt)

    def generate_full_video(
        self,
        script: Dict[str, Any],
        output_path: str,
    ) -> str:
        """Generate full video by creating each scene individually."""
        scenes = script.get("scenes", [])
        if not scenes:
            raise ValueError("El script no tiene escenas.")

        title = script.get("title", "Untitled")
        print(f"\n{'='*60}")
        print(f"[OVI] 🎬 Generación Local — '{title}'")
        print(f"[OVI]    {len(scenes)} escenas | GPU: Local")
        print(f"{'='*60}\n")

        clips: List[VideoClip] = []

        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_number", i + 1)
            prompt = scene.get("visual_prompt", scene.get("narration", ""))
            
            print(f"\n--- Escena {scene_num}/{len(scenes)} ---")
            clip = self.generate_scene(prompt=prompt, seed=scene.get("seed"))
            clips.append(clip)
            print(f"[OVI] ✅ Escena {scene_num} generada: {clip.file_path}")

        # Simple concatenation
        if len(clips) == 1:
            return clips[0].file_path

        return self._concatenate_clips(clips, output_path)

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _build_workflow(
        self,
        prompt: str,
        seed: int,
        negative_prompt: str = "",
    ) -> dict:
        """
        Build a ComfyUI workflow JSON for Ovi/LTX-2 video generation.
        
        NOTE: This is a template workflow. You'll need to customize it
        based on your specific ComfyUI node setup. See README.md for details.
        """
        # Parse resolution
        width, height = OVI_RESOLUTION.split("x")

        return {
            "prompt": {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "ovi_fp4.safetensors"},
                },
                "2": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "text": prompt,
                        "clip": ["1", 1],
                    },
                },
                "3": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "text": negative_prompt,
                        "clip": ["1", 1],
                    },
                },
                "4": {
                    "class_type": "EmptyLatentVideo",
                    "inputs": {
                        "width": int(width),
                        "height": int(height),
                        "length": 24,  # frames
                        "batch_size": 1,
                    },
                },
                "5": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": seed,
                        "steps": 20,
                        "cfg": 7.0,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                        "denoise": 1.0,
                        "model": ["1", 0],
                        "positive": ["2", 0],
                        "negative": ["3", 0],
                        "latent_image": ["4", 0],
                    },
                },
                "6": {
                    "class_type": "VAEDecode",
                    "inputs": {
                        "samples": ["5", 0],
                        "vae": ["1", 2],
                    },
                },
                "7": {
                    "class_type": "SaveAnimatedWEBP",
                    "inputs": {
                        "filename_prefix": "ovi_output",
                        "images": ["6", 0],
                    },
                },
            }
        }

    def _submit_and_wait(self, workflow: dict, prompt: str) -> str:
        """Submit workflow to ComfyUI and wait for results."""
        try:
            # Submit prompt
            response = httpx.post(
                f"{self.comfyui_url}/prompt",
                json=workflow,
                timeout=10,
            )

            if response.status_code != 200:
                raise Exception(f"ComfyUI error: {response.status_code} - {response.text}")

            prompt_id = response.json().get("prompt_id")
            print(f"[OVI] ⏳ Prompt enviado: {prompt_id}")

            # Poll for completion
            elapsed = 0
            while elapsed < OVI_TIMEOUT:
                time.sleep(5)
                elapsed += 5

                history = httpx.get(
                    f"{self.comfyui_url}/history/{prompt_id}",
                    timeout=10,
                ).json()

                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    # Find the output video/image
                    for node_id, output in outputs.items():
                        if "images" in output or "videos" in output:
                            items = output.get("videos", output.get("images", []))
                            if items:
                                filename = items[0]["filename"]
                                subfolder = items[0].get("subfolder", "")
                                # Download from ComfyUI
                                return self._download_output(filename, subfolder, prompt)
                    break

            # If we get here, something went wrong
            fallback_path = os.path.join(self.assets_dir, f"ovi_fallback_{int(time.time())}.txt")
            with open(fallback_path, "w") as f:
                f.write(f"Placeholder for: {prompt}")
            print(f"[OVI] ⚠️  Timeout o error. Archivo placeholder creado.")
            return fallback_path

        except Exception as e:
            print(f"[OVI] ❌ Error: {e}")
            fallback = os.path.join(self.assets_dir, f"ovi_error_{int(time.time())}.txt")
            with open(fallback, "w") as f:
                f.write(f"Error generating: {prompt}\n{str(e)}")
            return fallback

    def _download_output(self, filename: str, subfolder: str, prompt: str) -> str:
        """Download a generated file from ComfyUI's output."""
        url = f"{self.comfyui_url}/view"
        params = {"filename": filename, "subfolder": subfolder, "type": "output"}

        response = httpx.get(url, params=params, timeout=30)

        output_filename = f"ovi_{int(time.time())}_{filename}"
        output_path = os.path.join(self.assets_dir, output_filename)

        with open(output_path, "wb") as f:
            f.write(response.content)

        print(f"[OVI] 💾 Descargado: {output_path}")
        return output_path

    def _concatenate_clips(self, clips: List[VideoClip], output_path: str) -> str:
        """Concatenate clips using ffmpeg."""
        try:
            import subprocess

            concat_list = os.path.join(self.assets_dir, "_concat_list.txt")
            with open(concat_list, "w") as f:
                for clip in clips:
                    f.write(f"file '{clip.file_path.replace(chr(92), '/')}'\n")

            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", output_path],
                capture_output=True, text=True,
            )
            os.remove(concat_list)
            return output_path

        except FileNotFoundError:
            print("[OVI] ⚠️  ffmpeg no encontrado.")
            return clips[0].file_path
