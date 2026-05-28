"""
video_analyzer.py — Herramienta de Debug Visual basada en Gemini.

Sube un archivo de vídeo MP4 a la API de Google Gemini (requiere de Gemini 1.5 Pro)
para que haga un análisis de continuidad visual, lipsync, glitches y saltos entre
escenas que rompen el estilo o que revelen un mal uso de "continue" o "cut".
"""

import os
import time
from google import genai
from src.utils.api_key_manager import get_api_key_manager
from src.variables import GEMINI_MODEL_NAME

class VideoAnalyzer:
    def __init__(self, pod_config_path: str):
        self.pod_dir = os.path.dirname(pod_config_path)
        
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def analyze_video(self, video_path: str, episode_dir: str):
        """Sube un vídeo a Gemini para diagnosticar su cinematografía y transiciones."""
        if not os.path.exists(video_path):
            print(f"❌ Vídeo no encontrado: {video_path}")
            return
            
        print(f"\n[VideoAnalyzer] 📤 Subiendo vídeo a Gemini (esto puede tardar 1-2 minutos)...")
        print(f"   Archivo: {os.path.basename(video_path)}")
        video_file = self.client.files.upload(file=video_path)
        
        print(f"[VideoAnalyzer] ⏳ Vídeo subido (URI: {video_file.uri}). Esperando procesamiento activo...")
        while video_file.state.name == "PROCESSING":
            print(".", end="", flush=True)
            time.sleep(10)
            video_file = self.client.files.get(name=video_file.name)
            
        if video_file.state.name == "FAILED":
            print(f"\n[VideoAnalyzer] ❌ Falló el procesamiento del vídeo en los servidores de Google.")
            return
            
        print("\n[VideoAnalyzer] 🧠 Vídeo procesado. Lanzando diagnóstico técnico con {GEMINI_MODEL_NAME}...")
        
        prompt = (
            "Eres un Analista Técnico de Vídeo y Supervisor de Efectos Visuales (VFX) experto en cinematografía. "
            "Tu tarea es visualizar pacientemente este vídeo generado por IA escena a escena y buscar errores técnicos. "
            "Presta ESPECIAL ATENCIÓN a los saltos de cámara y transiciones.\n\n"
            "Por favor, elabora un reporte estructurado en Markdown analizando:\n"
            "1. **Glitches o Frames en Negro/Blanco:** Indica entre qué segundos ocurren.\n"
            "2. **Saltos Cortantes / Jump-cuts:** Indica el momento exacto donde la cámara salta de forma antinatural habiendo el mismo fondo, o si el personaje 'teletransporta' partes de su cuerpo.\n"
            "3. **Inconsistencia Visual:** Indica si el personaje cambia radicalmente de ropa, estilo artístico, o si el fondo cambia de golpe en un mismo plano.\n"
            "4. **Fallo en transiciones lógicas:** Si detectas que se usó un 'corte' pero que la IA intentó mezclar el plano anterior con el nuevo y creó una aberración.\n\n"
            "Sé totalmente objetivo, riguroso y listado. No te inventes fallos si no los hay, pero sé muy exigente."
        )

        try:
            model_name = GEMINI_MODEL_NAME 
            response = self.client.models.generate_content(
                model=model_name,
                contents=[video_file, prompt]
            )
            
            report_path = os.path.join(episode_dir, "video_analysis_report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"# Reporte de Análisis Visual\n\n**Vídeo:** {os.path.basename(video_path)}\n\n")
                f.write(response.text)
                
            print(f"[VideoAnalyzer] ✅ Análisis completado y guardado en:\n -> {report_path}")

        except Exception as e:
            print(f"\n[VideoAnalyzer] ❌ Error generando análisis: {e}")
        finally:
            print("[VideoAnalyzer] 🧹 Limpiando archivo remoto en Gemini...")
            try:
                self.client.files.delete(name=video_file.name)
            except Exception:
                pass
