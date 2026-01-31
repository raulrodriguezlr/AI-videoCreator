import os
import argparse
from dotenv import load_dotenv

# --- MONKEY PATCH FOR MOVIEPY COMPATIBILITY WITH NEW PILLOW ---
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ----------------------------------------------------------------

from src.engines.script_engine import ScriptGenerator
from src.engines.visual_engine import VisualGenerator
from src.engines.audio_engine import AudioGenerator
from src.engines.video_engine import VideoAssembler
from src.utils.memory_manager import MemoryManager

# Load env vars
load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="AI Video Creator Orchestrator")
    parser.add_argument("--topic", type=str, help="Topic for the video", required=False)
    parser.add_argument("--pod", type=str, default="kids_story", help="Pod name (folder in pods/)")
    args = parser.parse_args()

    # Paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    pod_config_path = os.path.join(project_root, "pods", args.pod, "config.json")
    
    if not os.path.exists(pod_config_path):
        print(f"Error: No configuration found for pod '{args.pod}' at {pod_config_path}")
        return

    print(f"🚀 Iniciando Pipeline para Pod: {args.pod}")

    # 1. Script Generation
    print("\n--- PASO 1: GUIÓN ---")
    script_engine = ScriptGenerator(pod_config_path)
    
    # If no topic provided, maybe get one from a list or ask (for now hardcoded default if missing)
    topic = args.topic if args.topic else "Tico aprende a compartir sus juguetes"
    print(f"Tema: {topic}")
    
    script = script_engine.generate_script(topic)
    if not script:
        print("Error generando guion. Abortando.")
        return
    
    print(f"Guion generado: {script.get('title')}")

    # 2. Visual Generation
    print("\n--- PASO 2: VISUALES ---")
    visual_engine = VisualGenerator(pod_config_path)
    visual_paths = visual_engine.generate_visuals(script)

    # 3. Audio Generation
    print("\n--- PASO 3: AUDIO ---")
    audio_engine = AudioGenerator(pod_config_path)
    audio_paths = audio_engine.generate_narration(script)

    # 4. Assembly
    print("\n--- PASO 4: ENSAMBLAJE ---")
    video_engine = VideoAssembler(pod_config_path)
    final_video_path = video_engine.assemble_video(script, visual_paths, audio_paths)

    # 5. Save Environment State (Memory)
    # Only save if everything succeeded
    print("\n--- PASO 5: MEMORIA ---")
    script_engine.save_episode_to_memory(script)

    print(f"\n✅ PROCESO COMPLETADO EXITOSAMENTE")
    print(f"📺 Video final disponible en: {final_video_path}")

if __name__ == "__main__":
    main()
