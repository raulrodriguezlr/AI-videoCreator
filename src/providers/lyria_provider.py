"""
lyria_provider.py — Generación de música de fondo usando ElevenLabs Sound Generation API.

ElevenLabs /v1/sound-generation genera efectos de sonido y música ambiental
desde un prompt de texto. Reemplaza el intento con Gemini TTS que solo
genera voz hablada, no música.
"""

import os
import requests
from src.variables import ELEVENLABS_API_KEY


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
            print("[LYRIA] ⚠️  ELEVENLABS_API_KEY no configurada en .env")

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
            print(f"[LYRIA] ♻️  Audio ya generado: {filename_mp3}")
            return output_path
        elif os.path.exists(output_path):
            print(f"[LYRIA] ⚠️  Archivo corrupto ({os.path.getsize(output_path)} bytes). Regenerando...")
            os.remove(output_path)

        if not ELEVENLABS_API_KEY:
            print("[LYRIA] ❌ No se puede generar audio: falta ELEVENLABS_API_KEY.")
            return None

        print(f"\n[LYRIA] 🎵 Generando música: '{prompt[:70]}...'")

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
                print(f"[LYRIA] ✅ Música guardada: {filename_mp3} ({size_kb} KB)")
                return output_path
            else:
                print(f"[LYRIA] ❌ Error ElevenLabs {response.status_code}: {response.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            print("[LYRIA] ❌ Timeout esperando respuesta de ElevenLabs (>120s)")
            return None
        except Exception as e:
            print(f"[LYRIA] ❌ Error generando música: {e}")
            return None
