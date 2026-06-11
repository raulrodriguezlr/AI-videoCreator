"""
variables.py — Configuración centralizada del proyecto AI-videoCreator v2.0

TODAS las configuraciones van aquí. No hay configuración hardcoded en ningún otro archivo.
Edita este archivo para cambiar el comportamiento del pipeline.

Requiere: .env con GOOGLE_API_KEY
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ==========================
# PIPELINE — Selección de provider
# ==========================
# 'veo' = Google Veo 3.1 API (producción, cloud, genera audio nativo)
# 'ltx' = LTX-2 via ComfyUI local (GPU local, no gasta tokens, genera audio)
VIDEO_PROVIDER = "veo"

# ==========================
# VEO — Google Veo 3.1 (Cloud)
# ==========================
# Modelos disponibles (junio 2026):
#   "veo-3.1-generate-preview"      → Máxima calidad, más lento (preview)
#   "veo-3.1-fast-generate-preview"  → Rápido, buena calidad (preview)
#   "veo-3.1-lite-generate-preview"  → Ligero (preview)
#   "veo-3.0-generate-001"          → GA estable
#   "veo-3.0-fast-generate-001"     → GA rápido
VEO_MODEL = "veo-3.0-generate-001"

# Resolución: "720p", "1080p", "4k"
VEO_RESOLUTION = "720p"

# Aspect ratio: "16:9" (landscape) | "9:16" (portrait/shorts)
VEO_ASPECT_RATIO = "16:9"

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
LTX_WIDTH = 768
LTX_HEIGHT = 512

# Video params
LTX_FPS = 24

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
ELEVENLABS_DEFAULT_VOICE_ID = "pNInz6obbf5cNed9uQcd"  # Voice genérica (Pippa u otra)
ELEVENLABS_DEFAULT_STABILITY = 0.5
ELEVENLABS_DEFAULT_SIMILARITY_BOOST = 0.8  # STS se beneficia de valores >= 0.8
ELEVENLABS_DEFAULT_STYLE = 0.3
ELEVENLABS_DEFAULT_USE_SPEAKER_BOOST = True
ELEVENLABS_DEFAULT_SPEED = 1.15

# ==========================
# LLM — Gemini (Script + Topic Generation + Images)
# ==========================
GEMINI_MODEL_NAME = "gemini-3.1-pro-preview"
IMAGEN_MODEL = "imagen-3.0-generate-002"
