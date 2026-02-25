import os
import base64
import wave
import struct
from google import genai
from google.genai import types
from src.utils.api_key_manager import get_api_key_manager
from src.variables import LYRIA_MODEL

class LyriaProvider:
    """
    Provider for generating audio using Google's Gemini TTS model.
    """
    # Gemini TTS returns raw PCM at 24000 Hz mono 16-bit
    PCM_SAMPLE_RATE = 24000
    PCM_CHANNELS = 1
    PCM_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

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
            filename: Output filename (e.g., 'bg_final.wav')

        Returns:
            Absolute path to the generated audio file, or None if failed.
        """
        output_path = os.path.join(self.output_dir, filename)

        # Validate cached file — only reuse if it's a proper WAV (>= 44 bytes header)
        if os.path.exists(output_path):
            if os.path.getsize(output_path) > 100:
                print(f"[LYRIA] ♻️  Audio ya generado: {filename}")
                return output_path
            else:
                print(f"[LYRIA] ⚠️  Archivo corrupto ({os.path.getsize(output_path)} bytes). Regenerando...")
                os.remove(output_path)

        print(f"\n[LYRIA] 🎵 Generando audio: '{prompt[:60]}...'")

        try:
            config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            )

            response = self.client.models.generate_content(
                model=LYRIA_MODEL,
                contents=prompt,
                config=config
            )

            # Extract audio from response
            audio_data = None
            mime_type = "audio/wav"
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                        audio_data = part.inline_data.data
                        mime_type = part.inline_data.mime_type
                        print(f"[LYRIA]    📦 Formato recibido: {mime_type}")
                        break
            else:
                print("[LYRIA] ❌ El modelo no devolvió una respuesta válida con audio.")

            if audio_data:
                # Decode base64 if needed
                if isinstance(audio_data, str):
                    audio_bytes = base64.b64decode(audio_data)
                else:
                    audio_bytes = audio_data

                # If mime_type is L16 or PCM, wrap in proper WAV container
                # Gemini TTS often returns audio/L16;rate=24000 or audio/pcm
                if "l16" in mime_type.lower() or "pcm" in mime_type.lower() or not mime_type.endswith("wav"):
                    # Extract sample rate from mime type if present (e.g. audio/L16;rate=24000)
                    sample_rate = self.PCM_SAMPLE_RATE
                    if "rate=" in mime_type:
                        try:
                            sample_rate = int(mime_type.split("rate=")[1].split(";")[0].strip())
                        except (ValueError, IndexError):
                            pass
                    print(f"[LYRIA]    🔧 Convirtiendo PCM → WAV ({sample_rate}Hz, {self.PCM_CHANNELS}ch, 16-bit)")
                    audio_bytes = self._pcm_to_wav(audio_bytes, sample_rate)

                with open(output_path, "wb") as f:
                    f.write(audio_bytes)

                print(f"[LYRIA] ✅ Audio guardado: {os.path.basename(output_path)} ({len(audio_bytes)//1024} KB)")
                self.key_manager.record_success()
                return output_path
            else:
                print("[LYRIA] ❌ La respuesta del modelo no contuvo datos de audio válidos.")

        except Exception as e:
            print(f"[LYRIA] ❌ Error generando audio con Lyria: {e}")
            if "exhausted" in str(e).lower() or "quota" in str(e).lower():
                self.key_manager.record_failure()

        return None

    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
        """Wrap raw PCM bytes in a proper WAV container."""
        import io
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buffer.getvalue()
