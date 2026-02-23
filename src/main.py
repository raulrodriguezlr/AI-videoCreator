"""
main.py — Orquestador principal del pipeline AI-videoCreator v2.0

Pipeline simplificado:
1. Determinar tema (manual, auto-topic, o generar ideas)
2. Generar guión cinematográfico (ScriptEngine → Gemini)
3. Generar vídeo nativo (VideoEngine → VeoProvider o OviProvider)
4. Guardar en memoria episódica (MemoryManager)

No más: VisualEngine, AudioEngine, MoviePy, Pillow mocks.
El vídeo se genera nativamente con audio sincronizado.
"""

import os
import argparse
import json
from dotenv import load_dotenv

from src.engines.script_engine import ScriptGenerator
from src.engines.video_engine import VideoEngine
from src.engines.topic_engine import TopicEngine
from src.utils.memory_manager import MemoryManager

# Load env vars
load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="AI Video Creator v2.0")
    parser.add_argument(
        "--topic", type=str, help="Tema para el vídeo (modo manual)", required=False
    )
    parser.add_argument(
        "--pod", type=str, help="Nombre del pod (carpeta en pods/). Obligatorio para generar vídeo."
    )
    parser.add_argument(
        "--auto-topic", action="store_true", help="Generar tema automáticamente con IA"
    )
    parser.add_argument(
        "--generate-topics",
        type=int,
        metavar="N",
        help="Generar N ideas de temas y salir (sin crear vídeo)",
    )
    parser.add_argument(
        "--check-provider",
        action="store_true",
        help="Verificar que el provider de vídeo está disponible (no requiere --pod)",
    )
    args = parser.parse_args()

    # --- Mode: Check provider (no requiere pod) ---
    if args.check_provider:
        from src.variables import VIDEO_PROVIDER
        print(f"🔍 Verificando provider '{VIDEO_PROVIDER}'...")

        if VIDEO_PROVIDER == "veo":
            try:
                from google import genai
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    print("❌ GOOGLE_API_KEY no encontrada en .env")
                    return
                client = genai.Client(api_key=api_key)
                print(f"✅ Provider 'veo' disponible y listo")
            except Exception as e:
                print(f"❌ Provider 'veo' NO disponible: {e}")
        elif VIDEO_PROVIDER == "ovi":
            try:
                import httpx
                from src.variables import OVI_COMFYUI_URL
                response = httpx.get(f"{OVI_COMFYUI_URL}/system_stats", timeout=5)
                if response.status_code == 200:
                    print(f"✅ Provider 'ovi' disponible en {OVI_COMFYUI_URL}")
                else:
                    print(f"❌ Provider 'ovi' respondió con status {response.status_code}")
            except Exception as e:
                print(f"❌ Provider 'ovi' NO disponible: {e}")
        else:
            print(f"❌ Provider '{VIDEO_PROVIDER}' no reconocido")
        return

    # Para todo lo demás, --pod es obligatorio
    if not args.pod:
        print("❌ Error: Debes especificar un pod con --pod <nombre>")
        print("   Ejemplo: python -m src.main --pod mi_pod --auto-topic")
        print("   Los pods están en la carpeta pods/")
        return

    # Paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    pod_config_path = os.path.join(project_root, "pods", args.pod, "config.json")

    if not os.path.exists(pod_config_path):
        print(f"❌ Error: No se encontró configuración para pod '{args.pod}' en {pod_config_path}")
        return

    # --- Mode: Generate topics only ---
    if args.generate_topics:
        print(f"🧠 Generando {args.generate_topics} ideas de temas para '{args.pod}'...")
        topic_engine = TopicEngine(pod_config_path)
        topics = topic_engine.generate_topics(count=args.generate_topics)

        if topics:
            print(f"\n✅ {len(topics)} temas generados:\n")
            for idx, topic in enumerate(topics, 1):
                print(f"{'='*60}")
                print(f"TEMA {idx}: {topic.get('title')}")
                print(f"{'='*60}")
                print(f"Descripción: {topic.get('description')}")
                print(f"Valor educativo: {topic.get('educational_value')}")
                print(f"Emoción: {topic.get('target_emotion')}")
                if topic.get("references_episode"):
                    print(f"Referencia: {topic['references_episode']}")
                print()
        else:
            print("❌ No se pudieron generar temas")
        return

    # --- Mode: Full video creation ---
    from src.variables import VIDEO_PROVIDER
    print(f"\n{'='*60}")
    print(f"🚀 AI-videoCreator v2.0 — Pod: {args.pod}")
    print(f"   Provider: {VIDEO_PROVIDER}")
    print(f"{'='*60}\n")

    # Step 1: Determine topic
    if args.auto_topic:
        print("🧠 Generando tema automáticamente...")
        topic_engine = TopicEngine(pod_config_path)
        topic_data = topic_engine.get_next_topic()

        if not topic_data:
            print("❌ Error: No se pudo generar un topic automáticamente")
            return

        topic = topic_data.get("title")
        print(f"✅ Topic: {topic}")
        print(f"   Descripción: {topic_data.get('description')}\n")
    elif args.topic:
        topic = args.topic
    else:
        print("⚠️  No se especificó --topic ni --auto-topic, usando tema por defecto...")
        topic = "Tico aprende sobre la perseverancia"

    print(f"📝 Tema del episodio: {topic}\n")

    # Step 2: Script Generation
    print("--- PASO 1/3: GENERACIÓN DE GUIÓN ---")
    script_engine = ScriptGenerator(pod_config_path)

    script = script_engine.generate_script(topic)
    if not script:
        print("❌ Error generando guion. Abortando pipeline.")
        return

    print(f"✅ Guion generado: '{script.get('title')}'")
    print(f"   Escenas: {len(script.get('scenes', []))}")
    print(f"   Moraleja: {script.get('moral', 'N/A')}\n")

    # Save script to file for reference
    script_path = os.path.join(os.path.dirname(pod_config_path), "last_script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    print(f"   📄 Script guardado en: {script_path}\n")

    # Step 3: Video Generation (native, with audio)
    print("--- PASO 2/3: GENERACIÓN DE VÍDEO ---")
    video_engine = VideoEngine(pod_config_path)
    final_video_path = video_engine.generate(script)
    print(f"✅ Vídeo generado: {final_video_path}\n")

    # Step 4: Save to Memory
    print("--- PASO 3/3: GUARDANDO EN MEMORIA ---")
    script_engine.save_episode_to_memory(script)
    print(f"✅ Episodio guardado en memoria del universo\n")

    print(f"{'='*60}")
    print(f"✅ PROCESO COMPLETADO")
    print(f"{'='*60}")
    print(f"📺 Video: {final_video_path}")
    print(f"📝 Título: {script.get('title')}")
    print(f"🎬 Escenas: {len(script.get('scenes', []))}")
    print()


if __name__ == "__main__":
    main()
