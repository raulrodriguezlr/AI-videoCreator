"""
main.py — Orquestador principal del pipeline AI-videoCreator v2.0

Pipeline simplificado:
1. Determinar tema (manual, auto-topic, o generar ideas)
2. Generar guión cinematográfico (ScriptEngine → Gemini)
3. Generar vídeo nativo (VideoEngine → VeoProvider o LtxProvider)
4. Guardar en memoria episódica (MemoryManager)

No más: VisualEngine, AudioEngine, MoviePy, Pillow mocks.
El vídeo se genera nativamente con audio sincronizado.
"""

import os
import sys
import argparse
import json
import httpx
from dotenv import load_dotenv

# Reconfigure stdout to utf-8 to handle emojis in Windows cmd/powershell
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from src.engines.script_engine import ScriptGenerator
from src.engines.video_engine import VideoEngine
from src.engines.topic_engine import TopicEngine
from src.utils.api_key_manager import get_api_key_manager
from src.utils.episode_manager import EpisodeManager
from src.utils.topic_manager import TopicManager
from src.utils.memory_manager import MemoryManager
from src.utils.progress_manager import ProgressManager
from src.utils.resume_handler import resume_episode
from src.variables import VIDEO_PROVIDER

# Load env vars
load_dotenv()


def run_interactive_menu(pod_name, pod_config_path, topic_mgr, episode_mgr):
    """
    Menú interactivo completo (Fase 6).
    """
    while True:
        print(f"\n{'='*60}")
        print(f"🎬 AI-videoCreator — Pod: {pod_name}")
        print(f"{'='*60}")
        print("\n¿Qué quieres hacer?")
        print("1. 📝 Ver temas disponibles")
        print("2. 🆕 Generar nuevos temas con IA")
        print("3. ▶️  Crear vídeo completo (Auto Topic)")
        print("4. 🔄 Continuar episodio incompleto")
        print("5. 📋 Ver episodios generados")
        print("6. ❌ Borrar un tema")
        print("7. 🎯 Crear vídeo de un tema específico")
        print("0. Salir")
        
        choice = input("\n> ").strip()

        if choice == "0":
            break
        elif choice == "1":
            topic_mgr.print_topics_table()
        elif choice == "2":
            count_str = input("¿Cuántos temas quieres generar? [3]: ").strip()
            count = int(count_str) if count_str.isdigit() else 3
            print(f"🧠 Generando {count} temas...")
            engine = TopicEngine(pod_config_path)
            topics = engine.generate_topics(count)
            if topics:
                added = topic_mgr.add_topics(topics)
                print(f"✅ Guardados {added} temas nuevos.")
                topic_mgr.print_topics_table()
        elif choice == "3":
            # Delegate to standard flow but with auto_topic
            topic_data = topic_mgr.pick_next()
            if not topic_data:
                print("⚠️ No hay temas pendientes. Generando uno automáticamente...")
                engine = TopicEngine(pod_config_path)
                topics = engine.generate_topics(3)
                if topics:
                    topic_mgr.add_topics(topics)
                    topic_data = topic_mgr.pick_next()
                
            if not topic_data:
                print("❌ Error: No se pudo generar un tema automáticamente.")
            else:
                print(f"✅ Usando tema: {topic_data['title']}")
                prompt_full_video(pod_name, pod_config_path, topic_data['title'], topic_mgr, episode_mgr, topic_id=topic_data['id'])
        elif choice == "4":
            # Find all incomplete episodes
            pod_output_dir = os.path.join("pods", pod_name, "output")
            incomplete_episodes = []
            if os.path.exists(pod_output_dir):
                for name in sorted(os.listdir(pod_output_dir)):
                    ep_dir = os.path.join(pod_output_dir, name)
                    if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
                        continue
                    progress_file = os.path.join(ep_dir, "progress.json")
                    if os.path.exists(progress_file):
                        try:
                            with open(progress_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            if data.get("status") != "completed":
                                completed = sum(1 for s in data.get('scenes', []) if s.get('status') == 'completed')
                                total = data.get('total_scenes', '?')
                                incomplete_episodes.append({
                                    "dir": ep_dir,
                                    "name": name,
                                    "title": data.get("title", name),
                                    "clips": f"{completed}/{total}",
                                })
                        except (json.JSONDecodeError, IOError):
                            continue

            if not incomplete_episodes:
                print("✅ No hay episodios incompletos.")
            else:
                print("\n🔄 Episodios incompletos:\n")
                for idx, ep in enumerate(incomplete_episodes, 1):
                    print(f"  {idx}. {ep['title']} ({ep['clips']} clips)")
                pick = input(f"\nElige episodio (1-{len(incomplete_episodes)}): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(incomplete_episodes):
                    chosen = incomplete_episodes[int(pick) - 1]
                    print(f"🔄 Continuando: {chosen['title']}")
                    resume_episode(chosen['dir'], pod_name)
                else:
                    print("❌ Selección no válida.")
        elif choice == "5":
            episode_mgr.print_episodes_table()
        elif choice == "6":
            topic_mgr.print_topics_table()
            tid = input("ID del tema a borrar (ej: topic_001): ").strip()
            if tid and topic_mgr.delete_topic(tid):
                print("✅ Borrado correctamente.")
            elif tid:
                print("❌ No encontrado.")
        elif choice == "7":
            pending = topic_mgr.get_pending()
            if not pending:
                print("⚠️ No hay temas pendientes. Usa la opción 2 para generar nuevos.")
            else:
                print("\n🎯 Temas pendientes:")
                for idx, t in enumerate(pending, 1):
                    print(f"  {idx}. {t['title']}")
                pick = input(f"\nElige tema (1-{len(pending)}): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(pending):
                    chosen = pending[int(pick) - 1]
                    print(f"✅ Seleccionado: {chosen['title']}")
                    prompt_full_video(pod_name, pod_config_path, chosen['title'], topic_mgr, episode_mgr, topic_id=chosen['id'])
                else:
                    print("❌ Selección no válida.")
        else:
            print("❌ Opción no válida.")

def prompt_full_video(pod_name, pod_config_path, topic, topic_mgr, episode_mgr, topic_id=None):
    """Ejecuta el pipeline completo de vídeo (extraído de main para reutilización)."""
    print(f"\n📝 Tema del episodio: {topic}\n")
    print("--- PASO 1/3: GENERACIÓN DE GUIÓN ---")
    script_engine = ScriptGenerator(pod_config_path)

    script = script_engine.generate_script(topic)
    if not script:
        print("❌ Error generando guion. Abortando pipeline.")
        return

    print(f"✅ Guion generado: '{script.get('title')}'")
    print(f"   Escenas: {len(script.get('scenes', []))}\n")

    episode = episode_mgr.create_episode(topic, script)
    episode_id = episode["episode_id"]
    episode_dir = episode["episode_dir"]

    if topic_id:
        topic_mgr.mark_in_progress(topic_id, episode_id)

    # También guarda un last_script por compat
    with open(os.path.join(os.path.dirname(pod_config_path), "last_script.json"), "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)

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
            episode_dir=episode_dir,
            progress_manager=progress,
        )
        print(f"✅ Vídeo generado: {final_video_path}\n")
        
        if topic_id:
            topic_mgr.mark_completed(topic_id, episode_id)
            
    except Exception as e:
        print(f"❌ Error en generación de vídeo: {e}")
        print(f"📊 Estado guardado en: {episode_dir}/progress.json")
        print(f"   Puedes continuar usando la Opción 4 del menú interactivo o flag --resume")
        return

    print("--- PASO 3/3: GUARDANDO EN MEMORIA ---")
    script_engine.save_episode_to_memory(script)
    print(f"✅ Episodio guardado en memoria.\n")


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
    
    # --- Nuevos comandos (Fase 6) ---
    parser.add_argument(
        "--list-topics", action="store_true", help="Mostrar tabla de temas generados"
    )
    parser.add_argument(
        "--list-episodes", action="store_true", help="Mostrar tabla de episodios"
    )
    parser.add_argument(
        "--delete-topic", type=str, metavar="TOPIC_ID", help="Eliminar un tema por ID"
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Iniciar menú interactivo"
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
        elif VIDEO_PROVIDER in ("ltx", "ovi"):
            try:
                response = httpx.get(f"{LTX_COMFYUI_URL}/system_stats", timeout=5)
                if response.status_code == 200:
                    print(f"✅ Provider 'ltx' disponible en {LTX_COMFYUI_URL}")
                else:
                    print(f"❌ Provider 'ltx' respondió con status {response.status_code}")
            except Exception as e:
                print(f"❌ Provider 'ltx' NO disponible: {e}")
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
    pod_dir = os.path.join(project_root, "pods", args.pod)
    pod_config_path = os.path.join(pod_dir, "config.json")

    if not os.path.exists(pod_config_path):
        print(f"❌ Error: No se encontró configuración para pod '{args.pod}' en {pod_config_path}")
        return

    topic_mgr = TopicManager(pod_dir)
    episode_mgr = EpisodeManager(pod_dir)

    # --- Mode: Direct CLI commands ---
    if args.list_topics:
        print(f"📋 Temas para pod '{args.pod}':")
        topic_mgr.print_topics_table()
        return

    if args.list_episodes:
        print(f"🎬 Episodios para pod '{args.pod}':")
        episode_mgr.print_episodes_table()
        return

    if args.delete_topic:
        if topic_mgr.delete_topic(args.delete_topic):
            print(f"✅ Tema eliminado: {args.delete_topic}")
        else:
            print(f"❌ No se encontró el tema: {args.delete_topic}")
        return

    if args.interactive:
        run_interactive_menu(args.pod, pod_config_path, topic_mgr, episode_mgr)
        return

    # --- Mode: Generate topics only ---
    if args.generate_topics:
        print(f"🧠 Generando {args.generate_topics} ideas de temas para '{args.pod}'...")
        topic_engine = TopicEngine(pod_config_path)
        topics = topic_engine.generate_topics(count=args.generate_topics)

        if topics:
            added = topic_mgr.add_topics(topics)
            print(f"\n✅ {len(topics)} temas generados ({added} nuevos guardados):\n")
            topic_mgr.print_topics_table()
        else:
            print("❌ No se pudieron generar temas")
        return

    # --- Mode: Full video creation ---

    print(f"\n{'='*60}")
    print(f"🚀 AI-videoCreator v2.0 — Pod: {args.pod}")
    print(f"   Provider: {VIDEO_PROVIDER}")
    print(f"{'='*60}\n")

    # Step 1: Determine topic
    topic_id = None
    if args.auto_topic:
        print("🧠 Obteniendo siguiente tema...")
        topic_data = topic_mgr.pick_next()

        if not topic_data:
            print("⚠️ No hay temas pendientes. Generando de forma automática...")
            topic_engine = TopicEngine(pod_config_path)
            topics = topic_engine.generate_topics(count=3)
            if topics:
                topic_mgr.add_topics(topics)
                topic_data = topic_mgr.pick_next()

        if not topic_data:
            print("❌ Error: No se pudo generar un topic automáticamente")
            return

        topic = topic_data.get("title")
        topic_id = topic_data.get("id")
        print(f"✅ Topic seleccionado: {topic}")
        print(f"   Descripción: {topic_data.get('description')}\n")
    elif args.topic:
        topic = args.topic
    else:
        print("⚠️  No se especificó --topic ni --auto-topic, usando tema por defecto...")
        topic = "Tico aprende sobre la perseverancia"

    prompt_full_video(args.pod, pod_config_path, topic, topic_mgr, episode_mgr, topic_id=topic_id)


if __name__ == "__main__":
    main()
