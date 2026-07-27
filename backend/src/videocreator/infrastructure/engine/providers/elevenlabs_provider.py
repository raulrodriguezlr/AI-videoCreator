"""
elevenlabs_provider.py — Generación de voces de personajes usando ElevenLabs TTS.

ElevenLabs /v1/text-to-speech genera voces muy realistas y consistentes
para cada personaje, leyendo su 'elevenlabs_voice_id' del config.json.
"""

import os
import json
import requests
import structlog
from typing import Optional, Tuple, Dict, Any

log = structlog.get_logger(__name__)

from videocreator.infrastructure.engine.variables import (
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
            log.warning("elevenlabs.api_key_missing")

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
        
        if name_key in self.voice_map:
            voice_id = self.voice_map[name_key]
        elif name_key in ("narrador", "narrator"):
            voice_id = ELEVENLABS_DEFAULT_VOICE_ID
        else:
            # Fallback for unregistered characters: young adult neutral voice (Antoni)
            voice_id = "ErXwobaYiN019PkySvjV"
            
        char_settings = self.voice_settings_map.get(name_key, {})
        return voice_id, char_settings

    def _check_cache(self, output_path: str, prefix: str = "[ElevenLabs]") -> bool:
        """Check if a valid audio file already exists to avoid re-generating. Deletes invalid ones."""
        if os.path.exists(output_path):
            if os.path.getsize(output_path) > 1000:
                log.info("elevenlabs.audio_cached", file=os.path.basename(output_path))
                return True
            os.remove(output_path)
        return False

    def _save_response(self, response: requests.Response, output_path: str, prefix: str) -> Optional[str]:
        """Validate an HTTP response and save the audio payload to disk."""
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            size_kb = len(response.content) // 1024
            log.info("elevenlabs.audio_saved", file=os.path.basename(output_path), size_kb=size_kb)
            return output_path

        log.error("elevenlabs.api_error", status=response.status_code, body=response.text[:200])
        return None

    def _handle_request_exceptions(self, func, prefix: str) -> Optional[str]:
        """Wrapper to safely handle request exceptions."""
        try:
            return func()
        except requests.exceptions.Timeout:
            log.error("elevenlabs.request_timeout")
        except Exception as e:
            log.error("elevenlabs.request_error", error=str(e))
        return None

    def generate_dialogue(self, text: str, character_name: str, output_path: str) -> Optional[str]:
        """Generates TTS audio for a specific character."""
        if not text or not text.strip():
            return None

        import hashlib
        voice_id, char_settings = self._get_character_config(character_name)
        hash_str = hashlib.md5(f"{text}_{voice_id}".encode('utf-8')).hexdigest()[:8]
        base, ext = os.path.splitext(output_path)
        actual_output_path = f"{base}_{hash_str}{ext}"

        prefix = "[ElevenLabs TTS]"
        if self._check_cache(actual_output_path, prefix):
            return actual_output_path
            
        output_path = actual_output_path

        if not ELEVENLABS_API_KEY:
            log.error("elevenlabs.tts_api_key_missing")
            return None

        voice_id, char_settings = self._get_character_config(character_name)
        log.info("elevenlabs.tts_generating", character=character_name, voice_id=voice_id, text=text[:50])

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
            log.error("elevenlabs.sts_source_not_found", path=source_audio_path)
            return None

        import hashlib
        voice_id, char_settings = self._get_character_config(character_name)
        stat = os.stat(source_audio_path)
        hash_str = hashlib.md5(f"{stat.st_size}_{stat.st_mtime}_{voice_id}".encode('utf-8')).hexdigest()[:8]
        base, ext = os.path.splitext(output_path)
        actual_output_path = f"{base}_{hash_str}{ext}"

        if self._check_cache(actual_output_path, prefix):
            return actual_output_path
            
        output_path = actual_output_path

        if not ELEVENLABS_API_KEY:
            log.error("elevenlabs.sts_api_key_missing")
            return None

        voice_id, char_settings = self._get_character_config(character_name)
        log.info("elevenlabs.sts_converting", character=character_name, voice_id=voice_id)
        
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
