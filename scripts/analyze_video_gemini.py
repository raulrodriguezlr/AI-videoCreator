import argparse
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

from google import genai

# Cargar el .env del backend
backend_env = Path(__file__).resolve().parent.parent / "backend" / ".env"
load_dotenv(backend_env)

GEMINI_MODEL_NAME = "gemini-1.5-pro"

def main():
    parser = argparse.ArgumentParser(description="Analizar qué está pasando en un video entero usando la API de Google Gemini.")
    parser.add_argument("video", help="Ruta al archivo de video (.mp4)")
    args = parser.parse_args()
    
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[!] El video no existe: {video_path}")
        sys.exit(1)

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[!] No se encontró GOOGLE_API_KEY en backend/.env")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print(f"\n[VideoAnalyzer] Subiendo video a Gemini (esto puede tardar 1-2 minutos)...")
    print(f"   Archivo: {video_path.name}")
    try:
        video_file = client.files.upload(file=str(video_path))
    except Exception as e:
        print(f"[!] Error al subir el vídeo: {e}")
        sys.exit(1)

    print(f"[VideoAnalyzer] Video subido (URI: {video_file.uri}). Esperando procesamiento activo...")
    
    # Wait until processing is finished
    while video_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(10)
        video_file = client.files.get(name=video_file.name)
        
    if video_file.state.name == "FAILED":
        print(f"\n[VideoAnalyzer] Fallo el procesamiento del video en los servidores de Google.")
        sys.exit(1)

    print(f"\n[VideoAnalyzer] Video procesado. Lanzando diagnostico tecnico con {GEMINI_MODEL_NAME}...")

    prompt = (
        "Eres un Analista Técnico de Vídeo y Supervisor de Efectos Visuales (VFX) experto en cinematografía. "
        "Tu tarea es visualizar pacientemente este vídeo generado por IA escena a escena y buscar errores técnicos. "
        "Presta ESPECIAL ATENCIÓN a los saltos de cámara, encuadres cortados y renderizado de subtítulos.\n\n"
        "Por favor, elabora un reporte estructurado en Markdown analizando:\n"
        "1. **Encuadre (Smart Crop):** ¿Hay personajes cortados a la mitad por los lados de la pantalla? ¿Se pierde acción importante porque la cámara vertical no está centrada en la acción real?\n"
        "2. **Subtítulos/Texto:** ¿Hay cajas extrañas ('tofu boxes'), símbolos rotos o fallos ortográficos visuales en los subtítulos integrados?\n"
        "3. **Ritmo y Acción:** ¿Hay planos extremadamente largos sin acción, zooms apuntando a la nada, o falta de sentido narrativo?\n"
        "4. **Saltos Cortantes / Inconsistencia:** ¿El personaje se teletransporta, cambia radicalmente de estilo o se producen saltos en negro?\n\n"
        "Sé totalmente objetivo, riguroso y listado. No te inventes fallos si no los hay, pero sé muy exigente."
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=[video_file, prompt]
        )
        
        report_path = video_path.parent / f"analysis_{video_path.stem}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Reporte de Análisis Visual\n\n**Vídeo:** {video_path.name}\n\n")
            f.write(response.text)
            
        print(f"\n[VideoAnalyzer] Analisis completado. Guardado en:\n -> {report_path}")

        # Mostrar el resultado en consola
        print("\n" + "="*50)
        print("RESPUESTA DE GEMINI AL VIDEO COMPLETO:")
        print("="*50)
        print(response.text)
        print("="*50 + "\n")

    except Exception as e:
        print(f"\n[VideoAnalyzer] Error generando analisis: {e}")
    finally:
        print("[VideoAnalyzer] Limpiando archivo remoto en Gemini...")
        try:
            client.files.delete(name=video_file.name)
        except Exception as e:
            print(f"[!] No se pudo borrar el archivo remoto: {e}")

if __name__ == "__main__":
    main()
