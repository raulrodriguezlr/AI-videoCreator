"""
elevenlabs_provider.py — Generación de voces de personajes usando ElevenLabs TTS.

ElevenLabs /v1/text-to-speech genera voces muy realistas y consistentes
para cada personaje, leyendo su 'elevenlabs_voice_id' del config.json.
"""

import os
import json
import requests
from typing import Optional, Tuple, Dict, Any

from src.variables import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_TTS_MODEL,
    ELEVENLABS_STS_MODEL,
    ELEVENLABS_OUTPUT_FORMAT,
    ELEVENLABS_DEFAULT_STABILITY,
    ELEVENLABS_DEFAULT_SIMILARITY_BOOST,
    ELEVENLABS_DEFAULT_STYLE,
    ELEVENLABS_DEFAULT_USE_SPEAKER_BOOST,
    ELEVENLABS_DEFAULT_SPEED,
    ELEVENLABS_DEFAULT_VOICE_ID
)

class ElevenLabsProvider:
    """
    Provider for generating character dialogue using ElevenLabs API (TTS & STS).
    """
    API_URL_TTS = "https://api.elevenlabs.io/v1/text-to-speech"
    API_URL_STS = "https://api.elevenlabs.io/v1/speech-to-speech"

    def __init__(self, pod_config_path: str):
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)
        
        if not ELEVENLABS_API_KEY:
            print("[ElevenLabs] ⚠️  ELEVENLABS_API_KEY no configurada en .env o variables.")

        self.voice_map: Dict[str, str] = {}
        self.voice_settings_map: Dict[str, Dict[str, Any]] = {}

        self._load_config(pod_config_path)

    def _load_config(self, pod_config_path: str) -> None:
        """Load character voice configurations from the pod's config.json."""
        if not os.path.exists(pod_config_path):
            return
            
        with open(pod_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        for char in config.get("characters", []):
            name = char.get("name", "").lower()
            if not name:
                continue
                
            if voice_id := char.get("elevenlabs_voice_id"):
                self.voice_map[name] = voice_id
                
            self.voice_settings_map[name] = char.get("elevenlabs_voice_settings", {})

    def _get_character_config(self, character_name: str) -> Tuple[str, Dict[str, Any]]:
        """Retrieve voice_id and specific settings for a character."""
        name_key = character_name.lower()
        voice_id = self.voice_map.get(name_key, ELEVENLABS_DEFAULT_VOICE_ID)
        char_settings = self.voice_settings_map.get(name_key, {})
        return voice_id, char_settings

    def _check_cache(self, output_path: str, prefix: str = "[ElevenLabs]") -> bool:
        """Check if a valid audio file already exists to avoid re-generating. Deletes invalid ones."""
        if os.path.exists(output_path):
            if os.path.getsize(output_path) > 1000:
                print(f"{prefix} ♻️  Audio ya generado: {os.path.basename(output_path)}")
                return True
            os.remove(output_path)
        return False

    def _save_response(self, response: requests.Response, output_path: str, prefix: str) -> Optional[str]:
        """Validate an HTTP response and save the audio payload to disk."""
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            size_kb = len(response.content) // 1024
            print(f"{prefix} ✅ Audio guardado: {os.path.basename(output_path)} ({size_kb} KB)")
            return output_path
            
        print(f"{prefix} ❌ Error API {response.status_code}: {response.text[:200]}")
        return None

    def _handle_request_exceptions(self, func, prefix: str) -> Optional[str]:
        """Wrapper to safely handle request exceptions."""
        try:
            return func()
        except requests.exceptions.Timeout:
            print(f"{prefix} ❌ Timeout esperando respuesta de la API")
        except Exception as e:
            print(f"{prefix} ❌ Error en la petición: {e}")
        return None

    def generate_dialogue(self, text: str, character_name: str, output_path: str) -> Optional[str]:
        """Generates TTS audio for a specific character."""
        if not text or not text.strip():
            return None

        prefix = "[ElevenLabs TTS]"
        if self._check_cache(output_path, prefix):
            return output_path

        if not ELEVENLABS_API_KEY:
            print(f"{prefix} ❌ Falla: ELEVENLABS_API_KEY no encontrada.")
            return None

        voice_id, char_settings = self._get_character_config(character_name)
        print(f"\n{prefix} 🗣️  Generando diálogo para {character_name} ({voice_id}): '{text[:50]}...'")

        url = f"{self.API_URL_TTS}/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        payload = {
            "text": text,
            "model_id": char_settings.get("model_id", ELEVENLABS_TTS_MODEL),
            "voice_settings": {
                "stability": char_settings.get("stability", ELEVENLABS_DEFAULT_STABILITY),
                "similarity_boost": char_settings.get("similarity_boost", ELEVENLABS_DEFAULT_SIMILARITY_BOOST),
                "style": char_settings.get("style", ELEVENLABS_DEFAULT_STYLE),
                "use_speaker_boost": char_settings.get("use_speaker_boost", ELEVENLABS_DEFAULT_USE_SPEAKER_BOOST)
            },
            "speed": char_settings.get("speed", ELEVENLABS_DEFAULT_SPEED)
        }

        def _do_request():
            res = requests.post(url, json=payload, headers=headers, timeout=60.0)
            return self._save_response(res, output_path, prefix)

        return self._handle_request_exceptions(_do_request, prefix)

    def convert_voice(self, source_audio_path: str, character_name: str, output_path: str) -> Optional[str]:
        """Convert voice using ElevenLabs Speech-to-Speech API."""
        prefix = "[ElevenLabs STS]"
        
        if not os.path.exists(source_audio_path):
            print(f"{prefix} ❌ Audio fuente no encontrado: {source_audio_path}")
            return None

        if self._check_cache(output_path, prefix):
            return output_path

        if not ELEVENLABS_API_KEY:
            print(f"{prefix} ❌ Falla: ELEVENLABS_API_KEY no encontrada.")
            return None

        voice_id, char_settings = self._get_character_config(character_name)
        print(f"\n{prefix} 🔄 Convirtiendo voz a {character_name} ({voice_id})...")
        
        url = f"{self.API_URL_STS}/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "xi-api-key": ELEVENLABS_API_KEY
        }

        voice_settings = {
            "stability": char_settings.get("stability", ELEVENLABS_DEFAULT_STABILITY),
            "similarity_boost": max(ELEVENLABS_DEFAULT_SIMILARITY_BOOST, char_settings.get("similarity_boost", ELEVENLABS_DEFAULT_SIMILARITY_BOOST)),
            "style": char_settings.get("style", ELEVENLABS_DEFAULT_STYLE),
            "use_speaker_boost": char_settings.get("use_speaker_boost", ELEVENLABS_DEFAULT_USE_SPEAKER_BOOST)
        }

        data = {
            "model_id": ELEVENLABS_STS_MODEL,
            "output_format": ELEVENLABS_OUTPUT_FORMAT,
            "voice_settings": json.dumps(voice_settings)
        }

        def _do_request():
            # STS requires multipart form-data. Context manager ensures file is safely closed.
            with open(source_audio_path, "rb") as audio_file:
                files = {
                    "audio": (os.path.basename(source_audio_path), audio_file, "audio/wav")
                }
                res = requests.post(url, headers=headers, files=files, data=data, timeout=120.0)
            return self._save_response(res, output_path, prefix)

        return self._handle_request_exceptions(_do_request, prefix)
