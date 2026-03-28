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

def test_music_generation():
    """Prueba de música / audio ambiental via Gemini/Lyria"""
    print("\n3️⃣ Probando Audio Generation (Música/Ambiente)")
    
    # Text prompt for music/ambient audio
    text = "Cheerful orchestral forest music with flutes, gentle acoustic guitar, and soft magical chimes. No vocals. 30 seconds."
    
    try:
        # According to the web search, the API might expose audio generation 
        # via the same model or a specific audio model. Let's try the audio modality.
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
                with open("testing/ambient_google.wav", "wb") as f:
                    f.write(audio_data)
                print("✅ Guardado en testing/ambient_google.wav")
            else:
                print("❌ No inline_data found in response part")
    except Exception as e:
        print(f"Error en generation de música: {e}")

if __name__ == "__main__":
    test_music_generation()

