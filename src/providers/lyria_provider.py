import os
import base64
from google import genai
from google.genai import types
from src.utils.api_key_manager import get_api_key_manager
from src.variables import LYRIA_MODEL

class LyriaProvider:
    """
    Provider for generating audio using Google's experimental Lyria model 
    (lyria-realtime-exp) or other Gemini audio/TTS variants.
    """
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def generate_ambient_audio(self, prompt: str, filename: str) -> str:
        """
        Generates ambient background music or sound effects based on a text prompt.
        
        Args:
            prompt: Text description of the desired audio (e.g., "Calm forest ambiance, 10 seconds")
            filename: Output filename (e.g., 'scene_03_ambient.wav')
            
        Returns:
            Absolute path to the generated audio file, or None if failed.
        """
        output_path = os.path.join(self.output_dir, filename)
        
        # Don't regenerate if it already exists
        if os.path.exists(output_path):
            print(f"[LYRIA] ♻️  Audio ya generado: {filename}")
            return output_path
            
        print(f"\n[LYRIA] 🎵 Generando audio: '{prompt[:60]}...'")
        
        try:
            # We configure the request to ask for AUDIO modality
            config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            )
            
            response = self.client.models.generate_content(
                model=LYRIA_MODEL,
                contents=prompt,
                config=config
            )
            
            # Extract audio from response
            # Typically, Audio responses from Gemini are base64 encoded inline data
            audio_data = None
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                    audio_data = part.inline_data.data
                    break
                    
            if audio_data:
                # If the SDK returned bytes directly
                if isinstance(audio_data, str):
                    # It might be returning base64 string
                    audio_bytes = base64.b64decode(audio_data)
                else:
                    audio_bytes = audio_data
                    
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                
                print(f"[LYRIA] ✅ Audio guardado: {output_path}")
                self.key_manager.record_success()
                return output_path
            else:
                print("[LYRIA] ❌ La respuesta del modelo no contuvo datos de audio válidos.")
                
        except Exception as e:
            print(f"[LYRIA] ❌ Error generando audio con Lyria: {e}")
            if "exhausted" in str(e).lower() or "quota" in str(e).lower():
                self.key_manager.record_failure()
                
        return None
