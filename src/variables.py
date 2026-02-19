import os

# --- LLM / SCRIPTING ---
# Model to use for script generation. 
# Options: 'gemini-1.5-pro', 'gemini-3-pro-preview', 'gemini-pro'
GEMINI_MODEL_NAME = "gemini-3-pro-preview"

# --- AUDIO / TTS ---
# Default Voice ID (Adam) if none is specified in character config
ELEVENLABS_DEFAULT_VOICE_ID = "nPczCjzI2devNBz1zQrb" 

# Specific Voices
VOICE_ID_GEORGE = "JBFqnCBsd6RMkjVDRZzb" # Warm, Storyteller
VOICE_ID_JESSICA = "cgSgspJ2msm6clMCkdW9" # Playful, Bright is nice for Tico 
# Model for TTS generation
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
# Voice settings
ELEVENLABS_STABILITY = 0.5
ELEVENLABS_SIMILARITY_BOOST = 0.75

# --- VISUALS / IMAGE GENERATION ---
# Fallback mock mode if API Key is missing or for testing
MOCK_VISUALS_ENABLED = False  # Set to False to use real image generation
# Set to True to attempt using Gemini for mock images (if available)
GEMINI_MOCK_IMAGES = True 

# Image Generation Provider: 'huggingface' (FREE), 'gemini', or 'sjinn'
IMAGE_GENERATION_PROVIDER = "huggingface"  # Hugging Face Stable Diffusion - 100% FREE!

# Hugging Face Configuration (FREE API - https://huggingface.co/settings/tokens)
# Model options: 
# - stabilityai/stable-diffusion-xl-base-1.0 (Best quality, slower)
# - runwayml/stable-diffusion-v1-5 (Faster, good quality)
# - CompVis/stable-diffusion-v1-4 (Fast, decent quality)
HUGGINGFACE_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
HUGGINGFACE_IMAGE_SIZE = (1024, 1024)  # Width x Height
HUGGINGFACE_NUM_INFERENCE_STEPS = 30  # Higher = better quality but slower (20-50)
HUGGINGFACE_GUIDANCE_SCALE = 7.5  # How closely to follow prompt (7-15)

# Gemini Image Generation Models (for prompt enhancement only)
GEMINI_IMAGE_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
]
GEMINI_IMAGE_MODEL = GEMINI_IMAGE_MODELS[0]

# Image generation parameters
IMAGE_GENERATION_TIMEOUT = 60  # seconds (Stable Diffusion can take 30-60s)
IMAGE_ASPECT_RATIO = "16:9"
IMAGE_SAMPLE_COUNT = 1

# Legacy SJinn API (currently not implemented)
SJINN_MODEL_QUALITY = "quality"

# --- VIDEO ---
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

