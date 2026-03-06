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
VIDEO_PROVIDER = "ltx"

# ==========================
# VEO — Google Veo 3.1 (Cloud)
# ==========================
# Modelos disponibles:
#   "veo-3.1-generate-preview"        → Máxima calidad, más lento
#   "veo-3.1-fast-generate-preview"   → Rápido, buena calidad
#   "veo-2"                           → Anterior, sin audio nativo
VEO_MODEL = "veo-3.1-generate-preview"

# Resolución: "720p", "1080p", "4k"
VEO_RESOLUTION = "720p"

# Aspect ratio: "16:9" (landscape) | "9:16" (portrait/shorts)
VEO_ASPECT_RATIO = "16:9"

# Duración por clip: 4, 6 u 8 segundos
VEO_DURATION_SECONDS = 8

# Generación de personas: "allow_all" | "allow_adult" | "dont_allow" puede que sea en minusculas
VEO_PERSON_GENERATION = "allow_adult"

# Polling: cada cuántos segundos comprobar si el vídeo está listo
VEO_POLLING_INTERVAL = 10

# Timeout máximo de espera en segundos (6 min = 360s)
VEO_TIMEOUT = 360

# ==========================
# LTX-Video — Local Generation
# ==========================
# ==========================
# LTX-2 — Local Generation
# ==========================
# Configuración para usar la librería oficial ltx-pipelines con LTX-2 19B (Gemma3 + Audio)
LTX_MODELS_DIR = r"C:\Users\raulr\Documents\ComfyUI\models"
LTX_CHECKPOINT = "checkpoints/ltx-2-19b-dev-fp4.safetensors"
LTX_TEXT_ENCODER = "text_encoders/gemma-3-12b-it-qat-q4_0-unquantized"
LTX_DISTILLED_LORA = "loras/ltx-2-19b-distilled-lora-384.safetensors"
LTX_QUANTIZATION = "fp8-cast"     # Para 12GB VRAM

LTX_WIDTH = 768
LTX_HEIGHT = 512
LTX_NUM_FRAMES = 97               # Recommended for LTX-2 distilled: 97 frames (~4s)
LTX_FRAME_RATE = 24
LTX_INFERENCE_STEPS = 30
LTX_DURATION_SECONDS = 4
LTX_NEGATIVE_PROMPT = "worst quality, inconsistent motion, blurry, jittery, distorted"

# ==========================
# SCENE BUILDER — Lógica de construcción de vídeo
# ==========================
# Usar reference images para mantener consistencia de personaje
USE_REFERENCE_IMAGES = True

# Máximo de extensiones por clip (Veo soporta hasta 20)
SCENE_BUILDER_MAX_EXTENDS = 20

# narrative_phase → tier
SCENE_TIER_MAP = {
    # HERO → máxima calidad (escenas clave de la historia)
    "climax": "hero",
    "resolution": "hero",
    "introduction": "hero",

    # STANDARD → rápido pero buena calidad
    "rising_action": "standard",
    "falling_action": "standard",

    # FILLER → modelo más económico
    "transition": "filler",
    "establishing": "filler",

    # Backward compat (nombres legacy de prompts.json antiguos)
    "development": "standard",
    "conclusion": "hero",
}

# tier → modelo Veo
TIER_MODEL_MAP = {
    "hero": "veo-3.1-generate-preview",
    "standard": "veo-3.1-generate-preview",
    "filler": "veo-3.1-generate-preview",
}

# ==========================
# AUDIO — ElevenLabs Sound Generation
# ==========================
# Used for ambient background music generation (replaces Gemini TTS which only does speech)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# ==========================
# LLM — Gemini (Script + Topic Generation)
# ==========================
GEMINI_MODEL_NAME = "gemini-3.1-pro-preview"
#"gemini-3-pro-preview"

# ==========================
# OUTPUT
# ==========================
VIDEO_FPS = 24

# ==========================
# AUTOMATION (futuro)
# ==========================
# 'none' | 'n8n_local' | 'opal'
AUTOMATION_MODE = "none"
N8N_URL = "http://localhost:5678"
