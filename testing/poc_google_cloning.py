import os
import sys
import subprocess
import time
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

def test_voice_cloning():
    """Prueba de clonación de voz (Instant Custom Voice) usando un clip existente"""
    print("\n4️⃣ Probando Voice Cloning (Instant Custom Voice)")
    
    video_path = "pods/kids_story/output/ep_001_el_mapa_manchado/clips/clip_06.mp4"
    audio_path = "testing/reference_audio.wav"
    
    if not os.path.exists(video_path):
        print(f"❌ No se encontró el archivo de referencia: {video_path}")
        return

    # Extraer audio con ffmpeg para evitar error de "Image input modality not enabled"
    print(f"Extrayendo audio de {video_path}...")
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        print("Subiendo archivo de audio a Gemini API...")
        reference_file = client.files.upload(
            file=audio_path,
            config={'display_name': 'Tico Reference Voice Audio'}
        )
        print(f"Archivo subido: {reference_file.name}. Esperando a que esté ACTIVE...")
        
        while reference_file.state.name == "PROCESSING":
            print(".", end="", flush=True)
            time.sleep(2)
            reference_file = client.files.get(name=reference_file.name)
            
        if reference_file.state.name == "FAILED":
            print("\n❌ Error procesando el archivo.")
            return
            
        print(f"\nEstado: {reference_file.state.name}. Generando audio...")
        
        text = "¡Hola! Esta es mi nueva voz clonada extrayendo el audio del clip anterior."

        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=[
                reference_file,
                f"Use the voice from the attached audio to say: {text}"
            ],
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            )
        )
        
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                with open("testing/cloned_google_tts.wav", "wb") as f:
                    f.write(audio_data)
                print("✅ Guardado en testing/cloned_google_tts.wav")
            else:
                print("❌ No inline_data found en response part")
                
        # Cleanup
        client.files.delete(name=reference_file.name)
        if os.path.exists(audio_path):
            os.remove(audio_path)
        print("Archivos de referencia eliminados.")

    except Exception as e:
        print(f"Error en voice cloning: {e}")

if __name__ == "__main__":
    test_voice_cloning()
