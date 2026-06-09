"""
lyria_provider.py — Generación de música de fondo usando ElevenLabs Sound Generation API.

ElevenLabs /v1/sound-generation genera efectos de sonido y música ambiental
desde un prompt de texto. Reemplaza el intento con Gemini TTS que solo
genera voz hablada, no música.
"""

import os
import requests
import structlog
from videocreator.infrastructure.engine.variables import ELEVENLABS_API_KEY

log = structlog.get_logger(__name__)


class LyriaProvider:
    """
    Provider for generating ambient background music using ElevenLabs.
    """
    API_URL = "https://api.elevenlabs.io/v1/sound-generation"
    # Default duration for background music (seconds, max 22 for ElevenLabs)
    DEFAULT_DURATION = 22.0

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        if not ELEVENLABS_API_KEY:
            log.warning("lyria.api_key_missing")

    def generate_ambient_audio(self, prompt: str, filename: str) -> str:
        """
        Generates ambient background music or sound effects based on a text prompt.

        Args:
            prompt: Text description of the desired audio (e.g., "Cheerful acoustic guitar")
            filename: Output filename (e.g., 'bg_final.mp3')

        Returns:
            Absolute path to the generated audio file, or None if failed.
        """
        # Use .mp3 extension — ElevenLabs returns MP3
        base, _ = os.path.splitext(filename)
        filename_mp3 = base + ".mp3"
        output_path = os.path.join(self.output_dir, filename_mp3)

        # Validate cached file
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            log.info("lyria.audio_cached", file=filename_mp3)
            return output_path
        elif os.path.exists(output_path):
            log.warning("lyria.audio_corrupted", file=filename_mp3, size_bytes=os.path.getsize(output_path))
            os.remove(output_path)

        if not ELEVENLABS_API_KEY:
            log.error("lyria.api_key_missing_cannot_generate")
            return None

        log.info("lyria.generating", prompt=prompt[:70])

        try:
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            }
            payload = {
                "text": prompt,
                "duration_seconds": self.DEFAULT_DURATION,
                "prompt_influence": 0.3,  # Higher = follows prompt more closely
            }

            response = requests.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )

            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                size_kb = len(response.content) // 1024
                log.info("lyria.audio_saved", file=filename_mp3, size_kb=size_kb)
                return output_path
            else:
                log.error("lyria.api_error", status=response.status_code, body=response.text[:200])
                return None

        except requests.exceptions.Timeout:
            log.error("lyria.request_timeout")
            return None
        except Exception as e:
            log.error("lyria.generation_error", error=str(e))
            return None
