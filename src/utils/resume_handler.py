"""
resume_handler.py — Lógica para continuar episodios incompletos.

Separado de main.py para mantener el orquestador limpio.
Maneja tanto el modo explícito (ruta directa) como el modo smart (--resume last).
"""

import os
import json
from src.utils.progress_manager import ProgressManager
from src.engines.video_engine import VideoEngine


def resume_episode(resume_value: str, pod_name: str = None):
    """
    Resume an incomplete episode.

    Args:
        resume_value: "last" for auto-detect, or explicit path to episode dir.
        pod_name: Pod name (required when resume_value is "last").
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # --- Smart mode: "last" → find latest incomplete ---
    if resume_value == "last":
        if not pod_name:
            print("❌ Para usar --resume last necesitas --pod <nombre>")
            print("   Ejemplo: python -m src.main --pod kids_story --resume last")
            return

        pod_output_dir = os.path.join(project_root, "pods", pod_name, "output")
        episode_dir = _find_latest_incomplete_episode(pod_output_dir)

        if not episode_dir:
            print(f"✅ No hay episodios incompletos en '{pod_name}'")
            return
    else:
        # --- Explicit path mode ---
        episode_dir = resume_value
        if not os.path.isabs(episode_dir):
            episode_dir = os.path.join(project_root, episode_dir)

    # Load progress
    progress = ProgressManager(episode_dir)
    progress_data = progress.load_progress()

    if not progress_data:
        print(f"❌ No se encontró progress.json en {episode_dir}")
        return

    if progress_data["status"] == "completed":
        print(f"✅ Este episodio ya está completado: {progress_data['title']}")
        return

    print(f"\n{'='*60}")
    print(f"🔄 CONTINUANDO EPISODIO")
    print(f"{'='*60}")
    print(progress.get_status_summary())
    print()

    # Load the saved script
    script_path = os.path.join(episode_dir, "script.json")
    if not os.path.exists(script_path):
        print(f"❌ No se encontró script.json en {episode_dir}")
        return

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    resume_from = progress.get_resume_index()

    # Detect pod from episode dir path: pods/<pod>/output/<episode_id>/
    pod_dir = os.path.dirname(os.path.dirname(episode_dir))
    pod_config_path = os.path.join(pod_dir, "config.json")

    if not os.path.exists(pod_config_path):
        print(f"❌ No se encontró config.json del pod en {pod_config_path}")
        return

    video_engine = VideoEngine(pod_config_path)

    try:
        final_video_path = video_engine.generate(
            script,
            output_path=os.path.join(episode_dir, "final.mp4"),
            resume_from=resume_from,
            progress_manager=progress,
        )
        print(f"\n✅ Vídeo generado: {final_video_path}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print(progress.get_status_summary())
        print(f"\nUsa --resume {episode_dir} para reintentar")


def _find_latest_incomplete_episode(output_dir: str):
    """
    Scan output_dir for episode folders (ep_*) and return the most recent
    one with status != 'completed'. If multiple found, lets user choose.
    """
    if not os.path.exists(output_dir):
        return None

    incomplete = []

    for name in sorted(os.listdir(output_dir)):
        ep_dir = os.path.join(output_dir, name)
        if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
            continue

        progress_file = os.path.join(ep_dir, "progress.json")
        if not os.path.exists(progress_file):
            continue

        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") not in ("completed",):
                incomplete.append((ep_dir, data))
        except (json.JSONDecodeError, IOError):
            continue

    if not incomplete:
        return None

    if len(incomplete) == 1:
        ep_dir, data = incomplete[0]
        print(f"📂 Episodio incompleto encontrado: {data.get('title', os.path.basename(ep_dir))}")
        return ep_dir

    # Multiple incomplete — let user choose
    print(f"\n📂 {len(incomplete)} episodios incompletos encontrados:\n")
    for idx, (ep_dir, data) in enumerate(incomplete, 1):
        completed = sum(1 for s in data.get('scenes', []) if s.get('status') == 'completed')
        total = data.get('total_scenes', '?')
        print(f"  {idx}. {data.get('title', os.path.basename(ep_dir))}")
        print(f"     Status: {data.get('status')} | Clips: {completed}/{total}")
        print()

    try:
        choice = input("Elige episodio (número): ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(incomplete):
            return incomplete[idx][0]
        else:
            print("❌ Opción no válida")
            return None
    except (ValueError, EOFError):
        print("❌ Entrada no válida")
        return None
