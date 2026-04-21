import os
import json
from src.engines.script_engine import ScriptGenerator
from src.engines.reviewer_engine import ReviewerEngine
from src.engines.video_engine import VideoEngine
from src.utils.progress_manager import ProgressManager

class PipelineOrchestrator:
    """
    Abstrae el flujo central de generación del pipeline (Guion -> Video -> Memoria).
    Desacoplado de la CLI para ser invocado también desde una GUI.
    """
    def __init__(self, pod_name: str, pod_config_path: str, topic_mgr, episode_mgr):
        self.pod_name = pod_name
        self.pod_config_path = pod_config_path
        self.topic_mgr = topic_mgr
        self.episode_mgr = episode_mgr

    def run_full_pipeline(self, topic: str, topic_id: str = None) -> None:
        """Ejecuta el pipeline completo de vídeo para un tema específico."""
        print(f"\n📝 Tema del episodio: {topic}\n")
        print("--- PASO 1/4: GENERACIÓN DE GUIÓN ---")
        script_engine = ScriptGenerator(self.pod_config_path)

        script = script_engine.generate_script(topic)
        if not script:
            print("❌ Error generando guion. Abortando pipeline.")
            return

        print(f"✅ Guion borrador generado: '{script.get('title')}'")
        print(f"   Escenas: {len(script.get('scenes', []))}\n")

        print("--- PASO 2/4: REVISIÓN DEL GUION (Director) ---")
        reviewer_engine = ReviewerEngine(self.pod_config_path)
        refined_script = reviewer_engine.review_script(script)
        
        # Si fallase catastróficamente, usaremos el borrador
        if refined_script:
            script = refined_script

        episode = self.episode_mgr.create_episode(topic, script)
        episode_id = episode["episode_id"]
        episode_dir = episode["episode_dir"]

        if topic_id:
            self.topic_mgr.mark_in_progress(topic_id, episode_id)

        # También guarda un last_script por compat
        last_script_path = os.path.join(os.path.dirname(self.pod_config_path), "last_script.json")
        try:
            with open(last_script_path, "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

        print("--- PASO 3/4: GENERACIÓN DE VÍDEO ---")
        progress = ProgressManager(episode_dir)
        progress.create_progress(
            episode_id=episode_id,
            topic=topic,
            script=script,
            total_scenes=len(script.get("scenes", [])),
        )

        video_engine = VideoEngine(self.pod_config_path)
        try:
            final_video_path = video_engine.generate(
                script,
                output_path=os.path.join(episode_dir, "final.mp4"),
                episode_dir=episode_dir,
                progress_manager=progress,
            )
            print(f"✅ Vídeo generado: {final_video_path}\n")
            
            if topic_id:
                self.topic_mgr.mark_completed(topic_id, episode_id)
                
        except Exception as e:
            print(f"❌ Error en generación de vídeo: {e}")
            print(f"📊 Estado guardado en: {episode_dir}/progress.json")
            print(f"   Puedes continuar usando la Opción 4 del menú interactivo o flag --resume")
            return

        print("--- PASO 4/4: GUARDANDO EN MEMORIA ---")
        script_engine.save_episode_to_memory(script)
        print(f"✅ Episodio guardado en memoria.\n")
