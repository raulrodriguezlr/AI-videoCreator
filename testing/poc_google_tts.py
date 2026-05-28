import os
import sys
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Please install google-genai: pip install google-genai")
    sys.exit(1)

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("GOOGLE_API_KEY no encontrada.")
    sys.exit(1)

client = genai.Client(api_key=api_key)

def test_single_speaker():
    """Prueba de voz de Tico con expresividad (risas)"""
    print("\n1️⃣ Probando Single Speaker (Tico - Alegre con risas)")
    text = "¡Hola amigos! Soy Tico. [laughing] ¡Mirad lo que he encontrado en este árbol gigante!"
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Puck" # Puck and Aoede are good for cheerful voices
                        )
                    )
                )
            )
        )
        
        # Save output
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                with open("testing/tico_google_tts.wav", "wb") as f:
                    f.write(audio_data)
                print("✅ Guardado en testing/tico_google_tts.wav")
            else:
                print("❌ No inline_data found in response part")
    except Exception as e:
        print(f"Error en single speaker: {e}")

if __name__ == "__main__":
    test_single_speaker()
