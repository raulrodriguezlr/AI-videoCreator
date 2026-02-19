import os
import argparse
import json
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
from src.engines.topic_engine import TopicEngine
from src.utils.memory_manager import MemoryManager

# Load env vars
load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="AI Video Creator Orchestrator")
    parser.add_argument("--topic", type=str, help="Topic for the video (manual mode)", required=False)
    parser.add_argument("--pod", type=str, default="kids_story", help="Pod name (folder in pods/)")
    parser.add_argument("--auto-topic", action="store_true", help="Auto-generate a topic using AI")
    parser.add_argument("--generate-topics", type=int, metavar="N", help="Generate N topic ideas and exit (no video creation)")
    args = parser.parse_args()

    # Paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    pod_config_path = os.path.join(project_root, "pods", args.pod, "config.json")
    
    if not os.path.exists(pod_config_path):
        print(f"❌ Error: No configuration found for pod '{args.pod}' at {pod_config_path}")
        return
    
    # Mode 1: Generate topics only (no video creation)
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
                if topic.get('references_episode'):
                    print(f"Referencia: {topic['references_episode']}")
                print()
        else:
            print("❌ No se pudieron generar temas")
        return

    # Mode 2: Create video
    print(f"🚀 Iniciando Pipeline para Pod: {args.pod}\n")

    # Determine topic
    if args.auto_topic:
        print("🧠 Modo AUTO-TOPIC: Generando tema automáticamente...")
        topic_engine = TopicEngine(pod_config_path)
        topic_data = topic_engine.get_next_topic()
        
        if not topic_data:
            print("❌ Error: No se pudo generar un topic automáticamente")
            return
        
        topic = topic_data.get("title")
        print(f"✅ Topic generado: {topic}")
        print(f"   Descripción: {topic_data.get('description')}")
        print()
    elif args.topic:
        topic = args.topic
    else:
        # Default fallback
        print("⚠️  No se especificó --topic ni --auto-topic, usando tema por defecto...")
        topic = "Tico aprende sobre la perseverancia"
    
    print(f"📝 Tema del episodio: {topic}\n")

    # 1. Script Generation
    print("--- PASO 1/5: GENERACIÓN DE GUIÓN ---")
    script_engine = ScriptGenerator(pod_config_path)
    
    script = script_engine.generate_script(topic)
    if not script:
        print("❌ Error generando guion. Abortando pipeline.")
        return
    
    print(f"✅ Guion generado: '{script.get('title')}'")
    print(f"   Escenas: {len(script.get('scenes', []))}")
    print(f"   Moraleja: {script.get('moral', 'N/A')}\n")

    # 2. Visual Generation
    print("--- PASO 2/5: GENERACIÓN DE VISUALES ---")
    visual_engine = VisualGenerator(pod_config_path)
    visual_paths = visual_engine.generate_visuals(script)
    print(f"✅ {len(visual_paths)} visuales generados\n")

    # 3. Audio Generation
    print("--- PASO 3/5: GENERACIÓN DE AUDIO ---")
    audio_engine = AudioGenerator(pod_config_path)
    audio_paths = audio_engine.generate_narration(script)
    print(f"✅ {len(audio_paths)} pistas de audio generadas\n")

    # 4. Video Assembly
    print("--- PASO 4/5: ENSAMBLAJE DE VIDEO ---")
    video_engine = VideoAssembler(pod_config_path)
    final_video_path = video_engine.assemble_video(script, visual_paths, audio_paths)
    print(f"✅ Video ensamblado\n")

    # 5. Save to Memory
    print("--- PASO 5/5: GUARDANDO EN MEMORIA ---")
    script_engine.save_episode_to_memory(script)
    print(f"✅ Episodio guardado en memoria del universo\n")

    print("="*60)
    print("✅ PROCESO COMPLETADO EXITOSAMENTE")
    print("="*60)
    print(f"📺 Video final: {final_video_path}")
    print(f"📝 Título: {script.get('title')}")
    print(f"⏱️  Duración estimada: ~{sum(s.get('duration_est', 0) for s in script.get('scenes', []))} segundos")
    print()

if __name__ == "__main__":
    main()

