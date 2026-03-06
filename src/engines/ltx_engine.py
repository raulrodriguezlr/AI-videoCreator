"""
LtxEngine — Motor de generación de vídeo con LTX-2 (Lightricks).

Wrapper sobre el paquete oficial ltx-pipelines. Gestiona la carga del pipeline,
generación de vídeo (text-to-video e image-to-video), optimización de VRAM con
fallback automático (FP8 GPU → CPU offload), y exportación a .mp4.

No contiene lógica de negocio (Scene Builder, progress, etc.) — eso va en LtxProvider.
"""

import os
import logging
import torch
from typing import Optional, List
import cv2

# Import official lightricks ltx-pipelines
from ltx_pipelines.ti2vid_one_stage import TI2VidOneStagePipeline
from ltx_pipelines.utils.media_io import encode_video
from ltx_core.loader import LoraPathStrengthAndSDOps
from ltx_core.components.guiders import MultiModalGuiderParams
# Helper if you need strings for Enum parsing, but the QuantizationPolicy string usually passes if parsed by helper.
# Actually, the pipe accepts quantization string from the command line, we'll import if needed.
from ltx_pipelines.utils.args import ImageConditioningInput

logger = logging.getLogger(__name__)


class LtxEngine:
    """
    Motor de generación de vídeo LTX-2 v2 usando el paquete oficial `ltx-pipelines`.
    
    Responsabilidades:
    - Cargar el checkpoint LTX-2, Text Encoder (Gemma 3) localmente desde ComfyUI.
    - Gestionar VRAM vía FP8 quantization + CPU swap (nativo en la librería).
    - Text-to-Video (con Audio).
    - Image-to-Video.
    """

    def __init__(
        self,
        checkpoint_path: str,
        gemma_root: str,
        distilled_lora_path: Optional[str] = None,
        quantization: Optional[str] = "fp8-cast",
    ):
        self.checkpoint_path = checkpoint_path
        self.gemma_root = gemma_root
        self.distilled_lora_path = distilled_lora_path
        self.quantization_str = quantization
        
        self.pipeline = None
        self._cpu_offload_active = False

    # ──────────────────────────────────────────────
    # PIPELINE LIFECYCLE
    # ──────────────────────────────────────────────

    def load(self) -> None:
        """Load the official LTX pipeline for Text-to-Video and Audio."""
        if self.pipeline is not None:
            return

        logger.info(f"[LTX Engine] Loading official LTX-pipelines (LTX-2 19B)...")
        logger.info(f"  Checkpoint: {os.path.basename(self.checkpoint_path)}")
        logger.info(f"  Gemma3 Dir: {os.path.basename(self.gemma_root)}")
        
        loras = []
        if self.distilled_lora_path and os.path.exists(self.distilled_lora_path):
            from ltx_core.loader.sd_ops import SDOps
            loras.append(LoraPathStrengthAndSDOps(
                path=self.distilled_lora_path,
                strength=1.0,
                sd_ops=SDOps(name="lora")
            ))
            logger.info(f"  LoRA loaded: {os.path.basename(self.distilled_lora_path)}")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # In ltx_pipelines, string 'fp8-cast' is parsed internally or we pass it
        from ltx_core.quantization import QuantizationPolicy
        
        try:
            quant_policy = QuantizationPolicy.from_optional_string(self.quantization_str)
        except Exception:
            # Fallback direct use if parsing changes
            quant_policy = None
            if self.quantization_str == "fp8-cast":
                quant_policy = QuantizationPolicy.fp8_cast()

        self.pipeline = TI2VidOneStagePipeline(
            checkpoint_path=self.checkpoint_path,
            gemma_root=self.gemma_root,
            loras=tuple(loras),
            device=device,
            quantization=quant_policy,
        )

        logger.info("[LTX Engine] ✅ Pipeline oficial cargado correctamente.")

    def unload(self) -> None:
        """Free VRAM by destroying the pipeline."""
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None
            torch.cuda.empty_cache()
            logger.info("[LTX Engine] 🧹 Pipeline unloaded, VRAM freed")

    def is_loaded(self) -> bool:
        return self.pipeline is not None

    def check_availability(self) -> bool:
        if not torch.cuda.is_available():
            logger.error("[LTX Engine] CUDA no está disponible.")
            return False
        if not os.path.exists(self.checkpoint_path):
            logger.error(f"[LTX Engine] Falta checkpoint: {self.checkpoint_path}")
            return False
        if not os.path.exists(self.gemma_root):
            logger.error(f"[LTX Engine] Falta Gemma3 encoder: {self.gemma_root}")
            return False
        return True

    # ──────────────────────────────────────────────
    # VIDEO GENERATION
    # ──────────────────────────────────────────────

    def _generate(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: str,
        seed: int,
        images_path: Optional[str] = None,
        width: int = 768,
        height: int = 512,
        num_frames: int = 97,
        frame_rate: float = 24.0,
        num_inference_steps: int = 30,
    ) -> str:
        
        if not self.is_loaded():
            self.load()

        logger.info(f"[LTX Engine] Generando video+audio...")
        logger.info(f"  Prompt: {prompt[:80]}...")
        if images_path:
             logger.info(f"  Image Conditioning: {images_path}")
        logger.info(f"  Resolución: {width}x{height} | Frames: {num_frames} | Pasos: {num_inference_steps}")

        images = []
        if images_path and os.path.exists(images_path):
             images = [[images_path]] # Formato requerido por ImageConditioningInput (list of lists representing conditioning paths)

        # Default MultiModalGuiderParams used by LTX-2 1-stage
        video_guider = MultiModalGuiderParams(
            cfg_scale=3.0,
            stg_scale=1.0,
            rescale_scale=0.7,
            modality_scale=1.0, # a2v
            skip_step=0,
            stg_blocks=(),
        )
        audio_guider = MultiModalGuiderParams(
            cfg_scale=3.0,
            stg_scale=1.0,  
            rescale_scale=0.7,
            modality_scale=1.0, # v2a
            skip_step=0,
            stg_blocks=(),
        )

        video, audio = self.pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            num_inference_steps=num_inference_steps,
            video_guider_params=video_guider,
            audio_guider_params=audio_guider,
            images=images,
            enhance_prompt=False,
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # We always output just 1 chunk for standard scenes
        encode_video(video=video, fps=frame_rate, audio=audio, output_path=output_path, video_chunks_number=1)
        
        logger.info(f"[LTX Engine] ✅ Vídeo guardado en {output_path}")
        return output_path

    def generate_t2v(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: str,
        width: int = 768,
        height: int = 512,
        num_frames: int = 97,
        frame_rate: float = 24.0,
        num_inference_steps: int = 30,
        seed: int = 42,
    ) -> str:
        """Text-to-video generation using LTX-pipelines."""
        return self._generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            output_path=output_path,
            seed=seed,
            width=width,
            height=height,
            num_frames=num_frames,
            frame_rate=frame_rate,
            num_inference_steps=num_inference_steps,
        )

    def generate_i2v(
        self,
        prompt: str,
        image_path: str,
        negative_prompt: str,
        output_path: str,
        width: int = 768,
        height: int = 512,
        num_frames: int = 97,
        frame_rate: float = 24.0,
        num_inference_steps: int = 30,
        seed: int = 42,
    ) -> str:
        """Image-to-video generation using LTX-pipelines."""
        return self._generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            output_path=output_path,
            seed=seed,
            images_path=image_path,
            width=width,
            height=height,
            num_frames=num_frames,
            frame_rate=frame_rate,
            num_inference_steps=num_inference_steps,
        )

    # ──────────────────────────────────────────────
    # UTILS
    # ──────────────────────────────────────────────

    def extract_last_frame(self, video_path: str, output_image_path: str) -> bool:
        """Extrae el último frame de un MP4 y lo guarda como JPG/PNG."""
        if not os.path.exists(video_path):
            logger.error(f"[LTX Engine] Videopath doesn't exist: {video_path}")
            return False

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"[LTX Engine] Could not open video: {video_path}")
            return False

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            logger.warning("[LTX Engine] Video has 0 frames.")
            return False

        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            logger.error("[LTX Engine] Failed to read the last frame.")
            return False

        os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
        cv2.imwrite(output_image_path, frame)
        return True

