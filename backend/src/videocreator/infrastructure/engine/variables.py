"""
variables.py — Configuración centralizada del proyecto AI-videoCreator v2.0

TODAS las configuraciones van aquí. No hay configuración hardcoded en ningún otro archivo.
Edita este archivo para cambiar el comportamiento del pipeline.

Requiere: .env con GOOGLE_API_KEY

LEGACY SHIM: this module predates `shared/config.py`'s pydantic Settings. The
handful of constants below that overlap with `Settings` (model ids, fps,
resolutions, default voice) are now read from there — with this module's
former hardcoded values as the `Settings` defaults — so they pick up env/.env
overrides without touching every `engine/` import site. Everything else here
remains hardcoded as before. Slated for removal once `engine/` retires in
favor of the provider SDK.
"""

import os
from dotenv import load_dotenv

from videocreator.shared.config import get_settings

load_dotenv()

_s = get_settings()

# ==========================
# PIPELINE — Selección de provider
# ==========================
# 'veo' = Google Veo 3.1 API (producción, cloud, genera audio nativo)
# 'ltx' = LTX-2 via ComfyUI local (GPU local, no gasta tokens, genera audio)
VIDEO_PROVIDER = "veo"

# Proxy workflow (COMPETITIVE_ANALYSIS §9.4): iterar con un provider barato
# (LTX local / draft) y hacer SOLO el render final con el caro (Veo $/seg).
# DESACTIVADO a propósito: pendiente de que el resultado de LTX local
# convenza; activar cuando haya un provider de draft que merezca la pena.
PROXY_WORKFLOW_ENABLED = False

# ==========================
# VEO — Google Veo 3.1 (Cloud)
# ==========================
# Modelos disponibles (junio 2026):
#   "veo-3.1-generate-preview"      → Máxima calidad, más lento (preview)
#   "veo-3.1-fast-generate-preview"  → Rápido, buena calidad (preview)
#   "veo-3.1-lite-generate-preview"  → Ligero (preview)
#   "veo-3.0-generate-001"          → GA estable
#   "veo-3.0-fast-generate-001"     → GA rápido
# Settings-backed (override via VEO_MODEL env / .env) — see Settings.veo_model.
VEO_MODEL = _s.veo_model

# Resolución: "720p", "1080p", "4k"
# Settings-backed (override via VEO_RESOLUTION env / .env).
VEO_RESOLUTION = _s.veo_resolution

# Aspect ratio: "16:9" (landscape) | "9:16" (portrait/shorts)
# Settings-backed (override via VEO_ASPECT_RATIO env / .env).
VEO_ASPECT_RATIO = _s.veo_aspect_ratio

# Duración por clip: 4, 6 u 8 segundos
VEO_DURATION_SECONDS = 8


# Polling: cada cuántos segundos comprobar si el vídeo está listo
VEO_POLLING_INTERVAL = 10

# Timeout máximo de espera en segundos (6 min = 360s)
VEO_TIMEOUT = 360

# ==========================
# LTX — LTX-2 via ComfyUI (Local GPU)
# ==========================
# ComfyUI API endpoint
LTX_COMFYUI_URL = "http://127.0.0.1:8188"

# Model checkpoint (in ComfyUI/models/checkpoints/)
LTX_CHECKPOINT = "ltx-2-19b-dev-fp4.safetensors"

# Distilled LoRA (in ComfyUI/models/loras/)
LTX_LORA = "ltx-2-19b-distilled-lora-384.safetensors"
LTX_LORA_STRENGTH = 0.6

# Gemma 3 text encoder folder (in ComfyUI/models/text_encoders/)
# The exact path is resolved at runtime from ComfyUI (OS-agnostic)
LTX_TEXT_ENCODER = "gemma-3-12b-it-qat-q4_0-unquantized"

# Resolution (must be divisible by 64 — 12GB VRAM safe)
# Settings-backed (override via LTX_WIDTH / LTX_HEIGHT env / .env).
LTX_WIDTH = _s.ltx_width
LTX_HEIGHT = _s.ltx_height

# Video params
# Settings-backed (override via LTX_FPS env / .env).
LTX_FPS = _s.ltx_fps

# Sampling params
LTX_STEPS = 25
LTX_CFG = 7.0
LTX_DENOISE = 1.0

# Timeout de espera para ComfyUI (segundos)
LTX_TIMEOUT = 600

# ==========================
# LTX-Desktop — LTX models via the Lightricks LTX-Desktop app
# (github.com/Lightricks/LTX-Desktop). Local FastAPI backend that renders on the
# GPU and writes a file to disk; replaces the ComfyUI path.
# ==========================
# Artlist multi-model hub default model (overridden per-episode by the handler).
ARTLIST_MODEL = "kling-3.0"

LTX_DESKTOP_URL = "http://localhost:41954"
# Generation pipeline id (the `model` the app expects, e.g. "fast" / "pro").
LTX_DESKTOP_MODEL = "fast"
LTX_DESKTOP_RESOLUTION = "720p"
LTX_DESKTOP_FPS = 24
LTX_DESKTOP_ASPECT_RATIO = "16:9"
# A local render can take minutes; generous ceiling.
LTX_DESKTOP_TIMEOUT = 1800

# ==========================
# SCENE BUILDER — Lógica de construcción de vídeo
# ==========================
# Usar reference images para mantener consistencia de personaje
USE_REFERENCE_IMAGES = True

# Máximo de extensiones por clip (Veo soporta hasta 20)
SCENE_BUILDER_MAX_EXTENDS = 20


# ==========================
# AUDIO & VOZ — ElevenLabs
# ==========================
# Used for TTS (Text-to-Speech) and STS (Speech-to-Speech) dubbing, and ambient background music.
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Modelos
ELEVENLABS_TTS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_STS_MODEL = "eleven_multilingual_sts_v2"
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"

# Voice Settings por defecto (si el character no los tiene en config.json)
# Settings-backed (override via ELEVENLABS_DEFAULT_VOICE_ID env / .env).
ELEVENLABS_DEFAULT_VOICE_ID = _s.elevenlabs_default_voice_id  # Voice genérica (Pippa u otra)
ELEVENLABS_DEFAULT_STABILITY = 0.5
ELEVENLABS_DEFAULT_SIMILARITY_BOOST = 0.8  # STS se beneficia de valores >= 0.8
ELEVENLABS_DEFAULT_STYLE = 0.3
ELEVENLABS_DEFAULT_USE_SPEAKER_BOOST = True
ELEVENLABS_DEFAULT_SPEED = 1.15

# ==========================
# LLM — Gemini (Script + Topic Generation + Images)
# ==========================
GEMINI_MODEL_NAME = "gemini-3.1-pro-preview"
IMAGEN_MODEL = "imagen-4.0-generate-001"
