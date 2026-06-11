import argparse
import base64
import os
import subprocess
import sys
import tempfile
import urllib.request
import json
from pathlib import Path

# Configuración por defecto de Ollama
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llava:latest" # o llama3.2-vision
DEFAULT_FRAMES = 5

def extract_multiple_frames(video_path: Path, output_dir: Path, num_frames: int) -> list[Path]:
    """Extrae varios fotogramas repartidos por el video usando FFmpeg."""
    print(f"[*] Extrayendo {num_frames} frames de: {video_path}")
    
    # 1. Obtener la duración del video
    cmd_duration = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        duration_str = subprocess.check_output(cmd_duration, text=True).strip()
        duration = float(duration_str)
    except Exception as e:
        print(f"[!] Error al obtener duración con ffprobe: {e}")
        duration = 1.0 # default fallback

    # Calcular los tiempos en los que extraer (evitando exactamente el principio y el final)
    step = duration / (num_frames + 1)
    extracted_files = []

    for i in range(1, num_frames + 1):
        timestamp = step * i
        out_file = output_dir / f"frame_{i:02d}.jpg"
        
        cmd_extract = [
            "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
            "-vframes", "1", "-q:v", "2", str(out_file)
        ]
        try:
            subprocess.run(cmd_extract, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            extracted_files.append(out_file)
            print(f"  - Frame {i} extraído en el segundo {timestamp:.2f}")
        except Exception as e:
            print(f"[!] Error extrayendo frame {i} con ffmpeg: {e}")
            
    return extracted_files

def analyze_images_with_ollama(image_paths: list[Path], model: str, prompt: str):
    """Envía todas las imágenes a Ollama juntas para darle contexto del video completo."""
    print(f"[*] Enviando {len(image_paths)} fotogramas a Ollama (modelo: {model})...")
    
    images_base64 = []
    for path in image_paths:
        with open(path, "rb") as f:
            images_base64.append(base64.b64encode(f.read()).decode('utf-8'))

    payload = {
        "model": model,
        "prompt": prompt,
        "images": images_base64,
        "stream": False
    }

    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode('utf-8'))
    req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            print("\n" + "="*50)
            print("🤖 RESPUESTA DE OLLAMA AL VIDEO COMPLETO:")
            print("="*50)
            print(result.get("response", "Sin respuesta"))
            print("="*50 + "\n")
    except Exception as e:
        print(f"[!] Error contactando con Ollama: {e}")
        print("Asegúrate de que Ollama está en ejecución y el modelo está instalado ('ollama run llava' o 'ollama run llama3.2-vision').")

def main():
    parser = argparse.ArgumentParser(description="Analizar qué está pasando en un video entero usando FFmpeg y Ollama Vision.")
    parser.add_argument("video", help="Ruta al archivo de video (.mp4)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de visión local (defecto: {DEFAULT_MODEL})")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES, help=f"Número de fotogramas a extraer para dar contexto (defecto: {DEFAULT_FRAMES})")
    parser.add_argument("--prompt", default=(
        "Aquí tienes una secuencia de fotogramas cronológicos extraídos de un mismo vídeo. "
        "Basándote en toda la secuencia, descríbeme de forma general qué está ocurriendo, "
        "cómo evoluciona la acción, y dime si notas algún error como un mal encuadre (personajes cortados) "
        "o problemas de renderizado de texto (símbolos raros en lugar de letras)."
    ), help="Instrucción para el LLM.")
    
    args = parser.parse_args()
    video_path = Path(args.video)

    if not video_path.exists():
        print(f"[!] El video no existe: {video_path}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        frames = extract_multiple_frames(video_path, tmp_path, args.frames)
        if not frames:
            print("[!] No se pudo extraer ningún fotograma.")
            sys.exit(1)
            
        analyze_images_with_ollama(frames, args.model, args.prompt)

if __name__ == "__main__":
    main()
