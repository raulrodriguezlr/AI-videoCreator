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

        # Map character names to their voice IDs and settings
        self.voice_map = {}
        self.voice_settings_map = {}
        if os.path.exists(pod_config_path):
            with open(pod_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            for char in config.get("characters", []):
                name = char.get("name", "").lower()
                voice_id = char.get("elevenlabs_voice_id")
                if name and voice_id:
                    self.voice_map[name] = voice_id
                # Per-character voice settings (optional)
                voice_settings = char.get("elevenlabs_voice_settings", {})
                if name:
                    self.voice_settings_map[name] = voice_settings

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
        char_settings = self.voice_settings_map.get(character_name.lower(), {})
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
                "model_id": char_settings.get("model_id", "eleven_multilingual_v2"),
                "voice_settings": {
                    "stability": char_settings.get("stability", 0.4),
                    "similarity_boost": char_settings.get("similarity_boost", 0.75),
                    "style": char_settings.get("style", 0.5),
                    "use_speaker_boost": True
                },
                "speed": char_settings.get("speed", 1.15)
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

    def convert_voice(self, source_audio_path: str, character_name: str, output_path: str) -> Optional[str]:
        """
        Convert the voice in a source audio file to a target character's voice
        using ElevenLabs Speech-to-Speech API.

        Preserves the original timing, cadence, and intonation — only changes the voice.
        This is ideal for dubbing: take Veo's native lip-synced audio and convert
        it to the consistent ElevenLabs voice while keeping perfect sync.

        Args:
            source_audio_path: Path to the source audio (e.g., extracted from Veo clip).
            character_name: Name of the character (to lookup their voice ID).
            output_path: Where to save the converted audio file.

        Returns:
            Absolute path to the converted audio file, or None if failed.
        """
        if not os.path.exists(source_audio_path):
            print(f"[ElevenLabs STS] ❌ Audio fuente no encontrado: {source_audio_path}")
            return None

        # Validate cached file
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"[ElevenLabs STS] ♻️  Audio ya convertido: {os.path.basename(output_path)}")
            return output_path
        elif os.path.exists(output_path):
            os.remove(output_path)

        if not ELEVENLABS_API_KEY:
            print("[ElevenLabs STS] ❌ No se puede convertir: falta ELEVENLABS_API_KEY.")
            return None

        voice_id = self.voice_map.get(character_name.lower(), self.DEFAULT_VOICE_ID)
        print(f"\n[ElevenLabs STS] 🔄 Convirtiendo voz a {character_name} ({voice_id})...")

        try:
            url = f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "xi-api-key": ELEVENLABS_API_KEY
            }

            # STS uses multipart form data, not JSON
            with open(source_audio_path, "rb") as audio_file:
                files = {
                    "audio": (os.path.basename(source_audio_path), audio_file, "audio/wav")
                }
                data = {
                    "model_id": "eleven_multilingual_sts_v2",
                    "output_format": "mp3_44100_128"
                }

                response = requests.post(
                    url,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=120.0
                )

            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                size_kb = len(response.content) // 1024
                print(f"[ElevenLabs STS] ✅ Voz convertida: {os.path.basename(output_path)} ({size_kb} KB)")
                return output_path
            else:
                print(f"[ElevenLabs STS] ❌ Error {response.status_code}: {response.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            print("[ElevenLabs STS] ❌ Timeout esperando respuesta de ElevenLabs STS")
            return None
        except Exception as e:
            print(f"[ElevenLabs STS] ❌ Error convirtiendo voz: {e}")
            return None
