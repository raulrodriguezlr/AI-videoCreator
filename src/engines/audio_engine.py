from src.variables import (
    ELEVENLABS_DEFAULT_VOICE_ID, 
    ELEVENLABS_MODEL_ID, 
    ELEVENLABS_STABILITY, 
    ELEVENLABS_SIMILARITY_BOOST
)
from typing import Dict
import os
import json
import requests

class AudioGenerator:
    def __init__(self, pod_config_path: str):
        # ... (keep existing init)
        self.config = self._load_config(pod_config_path)
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.mock_mode = not self.api_key or self.api_key == "your_elevenlabs_api_key_here"
        
        # Ensure assets directory exists
        self.assets_dir = os.path.join(os.path.dirname(pod_config_path), "assets")
        os.makedirs(self.assets_dir, exist_ok=True)

    def _load_config(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def generate_narration(self, script: Dict) -> Dict[str, str]:
        # ... (keep existing implementation)
        audio_paths = {}
        print(f"--- Iniciando Generación de Audio ({'MODO MOCK' if self.mock_mode else 'MODO API REAL'}) ---")

        for i, scene in enumerate(script['scenes']):
            text = scene.get('audio_text')
            character_name = scene.get('character', 'Narrator')
            
            if not text:
                continue

            # Determine voice ID based on character
            voice_id = self._get_voice_id(character_name)
            
            output_filename = f"audio_{i+1:03d}_{character_name}.mp3"
            output_path = os.path.join(self.assets_dir, output_filename)
            
            if self.mock_mode:
                self._generate_mock_audio(text, output_path, i)
            else:
                self._generate_real_audio(text, voice_id, output_path)
            
            audio_paths[i] = output_path
        
        return audio_paths

    def _get_voice_id(self, character_name: str) -> str:
        for char in self.config.get("characters", []):
            if char["name"] == character_name:
                return char.get("voice_id", ELEVENLABS_DEFAULT_VOICE_ID)
        return ELEVENLABS_DEFAULT_VOICE_ID

    def _generate_mock_audio(self, text: str, path: str, index: int):
        # ... (keep existing mock implementation)
        print(f"[MOCK AUDIO] Generando para escena {index+1}: '{text[:30]}...'")
        try:
            os.system(f"say -o '{path}' --data-format=LEF32@22050 '{text}'")
            if not os.path.exists(path):
                raise Exception("System TTS failed")
        except Exception:
            with open(path, 'w') as f:
                f.write("Mock Audio Content")

    def _generate_real_audio(self, text: str, voice_id: str, output_path: str):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = {
            "text": text,
            "model_id": ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability": ELEVENLABS_STABILITY,
                "similarity_boost": ELEVENLABS_SIMILARITY_BOOST
            }
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            print(f"[API] Audio generado para: {output_path}")
        else:
            print(f"Error {response.status_code}: {response.text}")
            raise Exception("ElevenLabs API Error")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    generator = AudioGenerator("pods/kids_story/config.json")
    
    dummy_script = {
        "scenes": [
            {"audio_text": "Hola soy Tico, la ardilla exploradora.", "character": "Tico"}
        ]
    }
    
    generator.generate_narration(dummy_script)
