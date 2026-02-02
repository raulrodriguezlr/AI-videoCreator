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

# --- VISUALS ---
# Fallback mock mode if API Key is missing or for testing
MOCK_VISUALS_ENABLED = True 
# Set to True to attempt using Gemini/Imagen for mock images (if available)
GEMINI_MOCK_IMAGES = True 
# Image Generation Model (when we implement real API)
SJINN_MODEL_QUALITY = "quality"

# --- VIDEO ---
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
