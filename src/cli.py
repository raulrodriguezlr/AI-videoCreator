import os
import argparse
import json
import httpx
from dotenv import load_dotenv

from src.engines.topic_engine import TopicEngine
from src.utils.api_key_manager import get_api_key_manager
from src.utils.episode_manager import EpisodeManager
from src.utils.topic_manager import TopicManager
from src.utils.resume_handler import resume_episode
from src.variables import VIDEO_PROVIDER, LTX_COMFYUI_URL
from src.engines.pipeline_orchestrator import PipelineOrchestrator
from src.utils.manual_dubbing import ManualDubber
from src.utils.voice_manager import VoiceManager
from src.utils.video_analyzer import VideoAnalyzer
from src.utils.video_editor import VideoEditor
from src.utils.youtube_uploader import YoutubeUploader

load_dotenv()


def run_interactive_menu(pod_name, pod_config_path, topic_mgr, episode_mgr):
    """Menú interactivo completo (Fase 6)."""
    orchestrator = PipelineOrchestrator(pod_name, pod_config_path, topic_mgr, episode_mgr)
    
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
        print("8. 🎙️  Doblaje Manual (Aplicar STS a un vídeo nativo)")
        print("9. 🗣️  Gestor de Voces (Cambiar voces con ElevenLabs + Gemini)")
        print("10. 🕵️  Analizador de Vídeo (Debug visual con Gemini Pro)")
        print("11. ✂️  Editor de Vídeos (Unir clips a medida)")
        print("12. 📤  Subir episodio a YouTube")
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
                orchestrator.run_full_pipeline(topic_data['title'], topic_id=topic_data['id'])
        elif choice == "4":
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
                    orchestrator.run_full_pipeline(chosen['title'], topic_id=chosen['id'])
                else:
                    print("❌ Selección no válida.")
        elif choice == "8":
            dubber = ManualDubber(pod_name, pod_config_path, episode_mgr)
            dubber.run_interactive()
        elif choice == "9":
            voice_mgr = VoiceManager(pod_config_path)
            voice_mgr.interactive_voice_editor()
        elif choice == "10":
            analyzer = VideoAnalyzer(pod_config_path)
            pod_output_dir = os.path.join("pods", pod_name, "output")
            episodes_with_video = []

            if os.path.exists(pod_output_dir):
                for name in sorted(os.listdir(pod_output_dir)):
                    ep_dir = os.path.join(pod_output_dir, name)
                    if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
                        continue
                    final_mp4 = os.path.join(ep_dir, f"{name}.mp4")
                    final_dubbed = os.path.join(ep_dir, f"{name}_dubbed.mp4")
                    
                    if not os.path.exists(final_mp4):
                        final_mp4 = os.path.join(ep_dir, "final.mp4") # Legacy fallback
                    if not os.path.exists(final_dubbed):
                        final_dubbed = os.path.join(ep_dir, "final_dubbed.mp4") # Legacy fallback
                    
                    if os.path.exists(final_mp4):
                        episodes_with_video.append({"ep_dir": ep_dir, "name": f"{name} (Nativo)", "video": final_mp4})
                    if os.path.exists(final_dubbed):
                        episodes_with_video.append({"ep_dir": ep_dir, "name": f"{name} (Doblado)", "video": final_dubbed})

            if not episodes_with_video:
                print("❌ No hay episodios con vídeos finales generados para analizar.")
            else:
                print("\n🕵️ Elige un vídeo generado para someter a análisis visual:")
                for idx, ep in enumerate(episodes_with_video, 1):
                    print(f"  {idx}. {ep['name']} -> {os.path.basename(ep['video'])}")
                
                pick = input(f"\nSelecciona (1-{len(episodes_with_video)}): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(episodes_with_video):
                    chosen = episodes_with_video[int(pick) - 1]
                    analyzer.analyze_video(chosen["video"], chosen["ep_dir"])
                else:
                    print("❌ Selección no válida.")
        elif choice == "11":
            editor = VideoEditor(pod_name, pod_config_path)
            editor.run_interactive()
        elif choice == "12":
            uploader = YoutubeUploader(pod_name, pod_dir=os.path.join("pods", pod_name))
            pod_output_dir = os.path.join("pods", pod_name, "output")
            episodes_with_video = []

            if os.path.exists(pod_output_dir):
                for name in sorted(os.listdir(pod_output_dir)):
                    ep_dir = os.path.join(pod_output_dir, name)
                    if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
                        continue
                        
                    final_mp4 = os.path.join(ep_dir, f"{name}.mp4")
                    final_dubbed = os.path.join(ep_dir, f"{name}_dubbed.mp4")
                    final_manual = os.path.join(ep_dir, f"{name}_dubbed_manually.mp4")
                    
                    if not os.path.exists(final_mp4):
                        final_mp4 = os.path.join(ep_dir, "final.mp4") # Legacy
                    if not os.path.exists(final_dubbed):
                        final_dubbed = os.path.join(ep_dir, "final_dubbed.mp4") # Legacy
                    
                    videos = []
                    if os.path.exists(final_manual):
                        videos.append({"path": final_manual, "type": "Doblado Manualmente"})
                    if os.path.exists(final_dubbed):
                        videos.append({"path": final_dubbed, "type": "Doblado Automático"})
                    if os.path.exists(final_mp4):
                        videos.append({"path": final_mp4, "type": "Nativo (Sin voz/Texto)"})
                        
                    if videos:
                        episodes_with_video.append({
                            "ep_dir": ep_dir, 
                            "name": name,
                            "videos": videos
                        })

            if not episodes_with_video:
                print("❌ No hay episodios con vídeos generados listos para subir.")
            else:
                print("\n📤 Elige el episodio que quieres subir a YouTube:")
                for idx, ep in enumerate(episodes_with_video, 1):
                    print(f"  {idx}. {ep['name']} ({len(ep['videos'])} versiones)")
                
                pick = input(f"\nSelecciona episodio (1-{len(episodes_with_video)}): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(episodes_with_video):
                    chosen_ep = episodes_with_video[int(pick) - 1]
                    
                    print(f"\n📽️ Versiones disponibles para '{chosen_ep['name']}':")
                    for v_idx, vid in enumerate(chosen_ep['videos'], 1):
                        print(f"  {v_idx}. {vid['type']} -> {os.path.basename(vid['path'])}")
                        
                    v_pick = input(f"\nSelecciona qué versión subir (1-{len(chosen_ep['videos'])}): ").strip()
                    if v_pick.isdigit() and 1 <= int(v_pick) <= len(chosen_ep['videos']):
                        chosen_vid = chosen_ep['videos'][int(v_pick) - 1]
                        uploader.upload_video(chosen_vid['path'], chosen_ep['ep_dir'])
                    else:
                        print("❌ Selección de vídeo no válida.")
                else:
                    print("❌ Selección de episodio no válida.")
        else:
            print("❌ Opción no válida.")

def run_cli():
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
    
    # Comandos
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

    # --- Mode: Check provider ---
    if args.check_provider:
        print(f"🔍 Verificando provider '{VIDEO_PROVIDER}'...")
        if VIDEO_PROVIDER == "veo":
            try:
                key_mgr = get_api_key_manager()
                # Dummy call to load module since we assume client exists
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
    base_dir = os.path.dirname(os.path.abspath(__file__)) # This is src/
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

    orchestrator = PipelineOrchestrator(args.pod, pod_config_path, topic_mgr, episode_mgr)
    orchestrator.run_full_pipeline(topic, topic_id=topic_id)
