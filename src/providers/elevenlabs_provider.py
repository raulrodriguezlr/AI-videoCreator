"""
elevenlabs_provider.py — Generación de voces de personajes usando ElevenLabs TTS.

ElevenLabs /v1/text-to-speech genera voces muy realistas y consistentes
para cada personaje, leyendo su 'elevenlabs_voice_id' del config.json.
"""

import os
import json
import requests
from typing import Optional
from src.variables import ELEVENLABS_API_KEY

class ElevenLabsProvider:
    """
    Provider for generating character dialogue using ElevenLabs TTS.
    """
    API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
    # Fallback default voice ID if character has no specific voice ID in config
    DEFAULT_VOICE_ID = "pNInz6obbf5cNed9uQcd"  # Example (Pippa or similar)

    def __init__(self, pod_config_path: str):
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)
        
        if not ELEVENLABS_API_KEY:
            print("[ElevenLabs] ⚠️  ELEVENLABS_API_KEY no configurada en .env o variables.")

        # Map character names to their voice IDs
        self.voice_map = {}
        if os.path.exists(pod_config_path):
            with open(pod_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            for char in config.get("characters", []):
                name = char.get("name", "").lower()
                voice_id = char.get("elevenlabs_voice_id")
                if name and voice_id:
                    self.voice_map[name] = voice_id

    def generate_dialogue(self, text: str, character_name: str, output_path: str) -> Optional[str]:
        """
        Generates TTS audio for a specific character.

        Args:
            text: The dialogue text to speak.
            character_name: Name of the character (to lookup their voice ID).
            output_path: Where to save the generated .wav file.

        Returns:
            Absolute path to the generated audio file, or None if failed.
        """
        if not text or not text.strip():
            return None

        # Validate cached file
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"[ElevenLabs] ♻️  Audio ya generado: {os.path.basename(output_path)}")
            return output_path
        elif os.path.exists(output_path):
            os.remove(output_path)

        if not ELEVENLABS_API_KEY:
            print("[ElevenLabs] ❌ No se puede generar diálogo: falta ELEVENLABS_API_KEY.")
            return None

        voice_id = self.voice_map.get(character_name.lower(), self.DEFAULT_VOICE_ID)
        print(f"\n[ElevenLabs] 🗣️  Generando diálogo para {character_name} ({voice_id}): '{text[:50]}...'")

        try:
            url = f"{self.API_URL}/{voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=60.0
            )

            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                size_kb = len(response.content) // 1024
                print(f"[ElevenLabs] ✅ Audio guardado: {os.path.basename(output_path)} ({size_kb} KB)")
                return output_path
            else:
                print(f"[ElevenLabs] ❌ Error ElevenLabs {response.status_code}: {response.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            print("[ElevenLabs] ❌ Timeout esperando respuesta de ElevenLabs")
            return None
        except Exception as e:
            print(f"[ElevenLabs] ❌ Error generando diálogo: {e}")
            return None
