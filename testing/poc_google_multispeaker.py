import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("GOOGLE_API_KEY no encontrada.")
    sys.exit(1)

client = genai.Client(api_key=api_key)

def test_multi_speaker():
    """Prueba de diálogo entre Narrador y Tico en un solo archivo"""
    print("\n2️⃣ Probando Multi-Speaker (Narrador + Tico)")
    
    # In Gemini TTS, you can often define speakers by stating their names or using specific prompts.
    text = """
    Narrator (calm, warm male voice): And so, Tico arrived at the great river.
    Tico (energetic, high-pitched young boy, excited): [gasp] ¡Guau! ¡Es enorme! ¿Cómo cruzaré?
    Narrator (encouraging): But Tico wasn't afraid. He knew what to do.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            )
        )
        
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                with open("testing/multispeaker_google_tts.wav", "wb") as f:
                    f.write(audio_data)
                print("✅ Guardado en testing/multispeaker_google_tts.wav")
            else:
                print("❌ No inline_data found in response part")
    except Exception as e:
        print(f"Error en multi speaker: {e}")

if __name__ == "__main__":
    test_multi_speaker()
