import traceback
import torch

from ltx_pipelines.ti2vid_one_stage import TI2VidOneStagePipeline
from ltx_core.components.guiders import MultiModalGuiderParams
import ltx_pipelines.utils.model_ledger

# Monkey-patch text encoder to run on CPU
old_text_encoder = ltx_pipelines.utils.model_ledger.ModelLedger.text_encoder

def cpu_text_encoder(self):
    print(">>> Loading TEXT ENCODER on CPU to save VRAM! <<<")
    # Build on CPU and keep on CPU
    return self.text_encoder_builder.build(device=torch.device("cpu"), dtype=self.dtype).to("cpu").eval()

ltx_pipelines.utils.model_ledger.ModelLedger.text_encoder = cpu_text_encoder

try:
    print("Loading pipeline...")
    pipe = TI2VidOneStagePipeline(
        checkpoint_path=r"C:\Users\raulr\Documents\ComfyUI\models\checkpoints\ltx-2-19b-dev-fp4.safetensors",
        gemma_root=r"C:\Users\raulr\Documents\ComfyUI\models\text_encoders\gemma-3-12b-it-qat-q4_0-unquantized",
        loras=(),
        device=torch.device("cuda"),
    )
    print("Generating...")
    video_guider = MultiModalGuiderParams(cfg_scale=3.0, stg_scale=1.0, rescale_scale=0.7, modality_scale=1.0, skip_step=0, stg_blocks=())
    audio_guider = MultiModalGuiderParams(cfg_scale=3.0, stg_scale=1.0, rescale_scale=0.7, modality_scale=1.0, skip_step=0, stg_blocks=())
    
    video, audio = pipe(
        prompt="A simple test",
        negative_prompt="",
        seed=42,
        height=512,
        width=768,
        num_frames=9,
        frame_rate=24.0,
        num_inference_steps=1,
        video_guider_params=video_guider,
        audio_guider_params=audio_guider,
        images=[],
        enhance_prompt=False,
    )
    print("Success!")
except Exception as e:
    traceback.print_exc()
