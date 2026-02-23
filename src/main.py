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
import httpx
from dotenv import load_dotenv

from src.engines.script_engine import ScriptGenerator
from src.engines.video_engine import VideoEngine
from src.engines.topic_engine import TopicEngine
from src.utils.api_key_manager import get_api_key_manager
from src.utils.memory_manager import MemoryManager
from src.utils.progress_manager import ProgressManager
from src.utils.resume_handler import resume_episode
from src.variables import VIDEO_PROVIDER, OVI_COMFYUI_URL

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
    parser.add_argument(
        "--resume",
        type=str,
        nargs="?",
        const="last",
        metavar="EPISODE_DIR",
        help="Continuar episodio incompleto. Usa 'last' con --pod para el más reciente, o pasa la carpeta exacta Ej: python -m src.main --pod kids_story --resume last o python -m src.main --resume pods/kids_story/output/ep_001_tico_paciencia",
    )
    args = parser.parse_args()

    # --- Mode: Check provider (no requiere pod) ---
    if args.check_provider:
        print(f"🔍 Verificando provider '{VIDEO_PROVIDER}'...")

        if VIDEO_PROVIDER == "veo":
            try:
                key_mgr = get_api_key_manager()
                client = key_mgr.get_client()
                print(f"✅ Provider 'veo' disponible — {key_mgr.get_key_label()}")
            except Exception as e:
                print(f"❌ Provider 'veo' NO disponible: {e}")
        elif VIDEO_PROVIDER == "ovi":
            try:
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

    # --- Mode: Resume incomplete episode ---
    if args.resume is not None:
        resume_episode(resume_value=args.resume, pod_name=args.pod)
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

    # Create episode output directory
    pod_dir = os.path.dirname(pod_config_path)
    output_dir = os.path.join(pod_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Generate episode ID
    episode_num = len([d for d in os.listdir(output_dir)
                       if os.path.isdir(os.path.join(output_dir, d))
                       and d.startswith("ep_")]) + 1
    safe_title = topic[:30].replace(" ", "_").replace("'", "").replace('"', '')
    episode_id = f"ep_{episode_num:03d}_{safe_title}"
    episode_dir = os.path.join(output_dir, episode_id)
    os.makedirs(episode_dir, exist_ok=True)

    # Save script to episode dir
    script_path = os.path.join(episode_dir, "script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    print(f"   📄 Script guardado en: {script_path}\n")

    # Also save as last_script for backwards compat
    last_script_path = os.path.join(pod_dir, "last_script.json")
    with open(last_script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)

    # Step 3: Video Generation (native, with audio) — WITH PROGRESS TRACKING
    print("--- PASO 2/3: GENERACIÓN DE VÍDEO ---")

    progress = ProgressManager(episode_dir)
    progress.create_progress(
        episode_id=episode_id,
        topic=topic,
        script=script,
        total_scenes=len(script.get("scenes", [])),
    )

    video_engine = VideoEngine(pod_config_path)

    try:
        final_video_path = video_engine.generate(
            script,
            output_path=os.path.join(episode_dir, "final.mp4"),
            progress_manager=progress,
        )
        print(f"✅ Vídeo generado: {final_video_path}\n")
    except Exception as e:
        print(f"❌ Error en generación de vídeo: {e}")
        print(f"📊 Estado guardado en: {episode_dir}/progress.json")
        print(f"   Usa --resume {episode_dir} para continuar")
        print(f"\n{progress.get_status_summary()}")
        return

    # Step 4: Save to Memory
    print("--- PASO 3/3: GUARDANDO EN MEMORIA ---")
    script_engine.save_episode_to_memory(script)
    print(f"✅ Episodio guardado en memoria del universo\n")

    print(f"{'='*60}")
    print(f"✅ PROCESO COMPLETADO")
    print(f"{'='*60}")
    print(f"📺 Video: {final_video_path}")
    print(f"📁 Episodio: {episode_dir}")
    print(f"📝 Título: {script.get('title')}")
    print(f"🎬 Escenas: {len(script.get('scenes', []))}")
    print()


if __name__ == "__main__":
    main()
