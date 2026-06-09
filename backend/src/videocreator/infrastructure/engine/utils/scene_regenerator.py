import os
import json
from typing import List, Dict, Any
from videocreator.infrastructure.engine.engines.video_engine import VideoEngine
from videocreator.infrastructure.engine.providers.veo_provider import VeoProvider
from videocreator.infrastructure.engine.providers.base_provider import VideoClip
from videocreator.infrastructure.engine.utils.progress_manager import ProgressManager
from videocreator.infrastructure.engine.utils.video_editor import VideoEditor
from videocreator.infrastructure.engine.utils.youtube_generator import YoutubeMetadataGenerator

class SceneRegenerator:
    """
    Herramienta interactiva para arreglar episodios:
    - Rehacer una escena concreta
    - Regenerar metadata de YouTube
    """
    def __init__(self, pod_name: str, pod_config_path: str):
        self.pod_name = pod_name
        self.pod_config_path = pod_config_path
        self.pod_output_dir = os.path.join("pods", pod_name, "output")

    def run_interactive(self):
        print(f"\n{'='*60}")
        print(f"🛠️  HERRAMIENTAS DE CORRECCIÓN DE EPISODIOS")
        print(f"{'='*60}")

        if not os.path.exists(self.pod_output_dir):
            print(f"❌ No se encontró la carpeta de salida para el pod '{self.pod_name}'.")
            return

        # 1. Listar episodios disponibles
        episodes = []
        for name in sorted(os.listdir(self.pod_output_dir)):
            ep_dir = os.path.join(self.pod_output_dir, name)
            script_path = os.path.join(ep_dir, "script.json")
            if os.path.isdir(ep_dir) and name.startswith("ep_") and os.path.exists(script_path):
                episodes.append({"name": name, "dir": ep_dir, "script_path": script_path})

        if not episodes:
            print("❌ No hay episodios generados (o faltan script.json).")
            return

        print("\n📂 Episodios disponibles:")
        for idx, ep in enumerate(episodes, 1):
            print(f"  {idx}. {ep['name']}")

        pick = input(f"\nElige el episodio a corregir (1-{len(episodes)}): ").strip()
        if not pick.isdigit() or not (1 <= int(pick) <= len(episodes)):
            print("❌ Selección no válida.")
            return

        chosen_ep = episodes[int(pick) - 1]
        ep_dir = chosen_ep["dir"]
        script_path = chosen_ep["script_path"]

        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        print(f"\n¿Qué quieres hacer con el episodio '{chosen_ep['name']}'?")
        print("1. 🔄 Rehacer escenas concretas (Corregir glitch, audio o prompt)")
        print("2. 📝 Regenerar Metadatos de YouTube (Títulos, tags, SEO, etc.)")
        action_pick = input("\n> ").strip()

        if action_pick == "1":
            self._fix_scene(chosen_ep, script)
        elif action_pick == "2":
            self._regenerate_yt_metadata(chosen_ep, script)
        else:
            print("❌ Opción no válida.")

    def _regenerate_yt_metadata(self, chosen_ep: dict, script: dict):
        ep_dir = chosen_ep["dir"]
        print(f"\n📝 Regenerando metadatos de YouTube para '{chosen_ep['name']}'...")
        try:
            yt_generator = YoutubeMetadataGenerator()
            yt_generator.generate_and_save(script, ep_dir)
            print("✅ ¡Metadatos generados y guardados con éxito en la carpeta del episodio!")
        except Exception as e:
            print(f"❌ Error generando metadatos de YouTube: {e}")

    def _fix_scene(self, chosen_ep: dict, script: dict):
        ep_dir = chosen_ep["dir"]
        script_path = chosen_ep["script_path"]
        
        while True:
            # Recargar script por si se actualizó en la iteración anterior
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)

            scenes = script.get("scenes", [])
            if not scenes:
                print("❌ El script no tiene escenas.")
                return

            print(f"\n🎬 Escenas de {chosen_ep['name']}:")
            for i, sc in enumerate(scenes):
                scene_num = sc.get("scene_number", i + 1)
                prompt_preview = sc.get("visual_prompt", "")[:50] + "..."
                print(f"  {i + 1}. Escena {scene_num}: {prompt_preview}")

            scene_pick = input(f"\nElige la escena a rehacer (1-{len(scenes)}) o '0' para cancelar/terminar: ").strip()
            
            if scene_pick == "0":
                break

            if not scene_pick.isdigit() or not (1 <= int(scene_pick) <= len(scenes)):
                print("❌ Selección no válida.")
                continue

            scene_index = int(scene_pick) - 1
            scene = scenes[scene_index]
            scene_num = scene.get("scene_number", scene_index + 1)
            scene_num_str = f"{scene_num:02d}"

            print(f"\n{'='*40}")
            print(f"📝 MODIFICAR ESCENA {scene_num}")
            print(f"{'='*40}")
            
            current_vp = scene.get("visual_prompt", "")
            print(f"\n[Visual Prompt Actual]:\n{current_vp}\n")
            new_vp = input("Nuevo Visual Prompt (pulsa Enter para no cambiarlo): ").strip()
            if new_vp:
                scene["visual_prompt"] = new_vp
                print("✅ Visual Prompt actualizado.")

            current_at = scene.get("audio_text", "")
            print(f"\n[Texto de Audio Actual]:\n{current_at}\n")
            new_at = input("Nuevo texto (pulsa Enter para no cambiarlo): ").strip()
            if new_at:
                scene["audio_text"] = new_at
                print("✅ Audio de diálogo actualizado.")

            if new_vp or new_at:
                with open(script_path, "w", encoding="utf-8") as f:
                    json.dump(script, f, indent=2, ensure_ascii=False)
                print(f"💾 script.json guardado con los cambios.")

            print(f"\n🚀 Regenerando Escena {scene_num}...")
            
            veo = VeoProvider(self.pod_config_path)
            clips_dir = os.path.join(ep_dir, "clips")
            os.makedirs(clips_dir, exist_ok=True)
            
            narrative_phase = scene.get("narrative_phase", "")
            incoming_transition = scenes[scene_index - 1].get("transition_to_next", "cut") if scene_index > 0 else "scene_change"
            transition = scene.get("transition_to_next", "cut")
            scene_duration = scene.get("duration_seconds", 5)
            
            from videocreator.infrastructure.engine.utils.scene_context import SceneContextManager
            context_mgr = SceneContextManager(ep_dir, pod_config=veo.config)
            for prev_i in range(scene_index):
                context_mgr.update_after_scene(prev_i, scenes[prev_i], scenes[prev_i].get("transition_to_next", "cut"))
                
            continuity_context = context_mgr.get_continuity_context(incoming_transition)
            prompt = veo._build_cinematographic_prompt(
                scene, narrative_phase,
                incoming_transition=incoming_transition,
                continuity_context=continuity_context,
            )
            negative = scene.get("negative_prompt")
            
            ref_images = []
            consistency_cfg = veo.config.get("consistency", {})
            if consistency_cfg.get("generate_anchor_images", False):
                anchor_path = os.path.join(ep_dir, "assets", "anchor_character.png")
                if os.path.exists(anchor_path):
                    ref_images = [anchor_path]
            if not ref_images:
                ref_images = veo._get_character_reference_images()

            clips = []
            if scene_index > 0:
                prev_clip_path = os.path.join(clips_dir, f"clip_{scene_index:02d}.mp4")
                if os.path.exists(prev_clip_path):
                    clips.append(VideoClip(file_path=prev_clip_path, duration=5))

            try:
                clip = veo._generate_clip(
                    scene=scene, i=scene_index, clips=clips, transition=transition,
                    prompt=prompt, scene_duration=scene_duration,
                    ref_images=ref_images, negative=negative,
                    narrative_phase=narrative_phase, clips_dir=clips_dir,
                    incoming_transition=incoming_transition,
                    is_resume_bridge=True
                )
                
                print(f"🎙️ Generando nuevo doblaje para la escena...")
                veo._apply_dubbing(clip, scene, clips_dir, scene_num_str)
                
                progress_mgr = ProgressManager(ep_dir)
                progress_mgr.mark_scene_completed(scene_index, clip.file_path, "veo")
                
                print(f"\n✅ Clip de la escena {scene_num} regenerado con éxito: {clip.file_path}")
                if getattr(clip, 'dubbed_path', None):
                    print(f"✅ Clip doblado generado: {clip.dubbed_path}")
                    
            except Exception as e:
                result = veo._handle_scene_error(
                    e, i=scene_index, scene=scene, scene_num=scene_num,
                    clips=clips, transition=transition, prompt=prompt,
                    scene_duration=scene_duration, ref_images=ref_images,
                    negative=negative, narrative_phase=narrative_phase,
                    clips_dir=clips_dir, scene_num_str=scene_num_str,
                    progress_manager=None,
                    incoming_transition=incoming_transition,
                    is_resume_bridge=True
                )
                if result.get("clip"):
                    clip = result["clip"]
                    progress_mgr = ProgressManager(ep_dir)
                    progress_mgr.mark_scene_completed(scene_index, clip.file_path, "veo")
                    print(f"\n✅ Clip de la escena {scene_num} regenerado con éxito (tras cambiar API key): {clip.file_path}")
                    if getattr(clip, 'dubbed_path', None):
                        print(f"✅ Clip doblado generado: {clip.dubbed_path}")
                else:
                    print(f"❌ Error crítico regenerando la escena. No quedan cuotas disponibles.")
                
            ans_more = input("\n¿Hay alguna otra escena que quieras arreglar antes de montar el vídeo final? (S/n): ").strip().lower()
            if ans_more == 'n':
                break

        # Una vez terminado el bucle, montamos el episodio si el usuario quiere
        ans_remount = input("\n¿Quieres re-ensamblar el vídeo final del episodio ahora mismo? (S/n): ").strip().lower()
        if ans_remount != 'n':
            print("\n🔄 Re-ensamblando el episodio completo...")
            clips_dir = os.path.join(ep_dir, "clips")
            if not os.path.exists(clips_dir):
                print("❌ No hay carpeta de clips para ensamblar.")
                return
                
            all_files = sorted(os.listdir(clips_dir))
            clip_bases = set()
            for f in all_files:
                if f.endswith(".mp4") and f.startswith("clip_"):
                    base_num = f.replace("clip_", "").replace("_dubbed.mp4", "").replace(".mp4", "")
                    if base_num.isdigit():
                        clip_bases.add(int(base_num))
            
            clips_to_join = []
            for num in sorted(list(clip_bases)):
                num_str = f"{num:02d}"
                dubbed = f"clip_{num_str}_dubbed.mp4"
                native = f"clip_{num_str}.mp4"
                if dubbed in all_files:
                    clips_to_join.append(os.path.join(clips_dir, dubbed))
                elif native in all_files:
                    clips_to_join.append(os.path.join(clips_dir, native))
                    
            out_name = f"{chosen_ep['name']}_dubbed.mp4"
            output_path = os.path.join(ep_dir, out_name)
            
            editor = VideoEditor(self.pod_name, self.pod_config_path)
            clips_to_join = editor._normalize_clips(clips_to_join)
            
            concat_list_path = os.path.join(ep_dir, "_regenerator_concat_list.txt")
            try:
                import subprocess
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for cp in clips_to_join:
                        abs_path = os.path.abspath(cp).replace("\\", "/")
                        f.write(f"file '{abs_path}'\n")

                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", output_path]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"\n🎉 ¡Vídeo final actualizado correctamente!\n  -> {output_path}")
                
                # --- BACKGROUND AUDIO DISABLED ---
                # audio_dir = os.path.join(ep_dir, "audio")
                # if os.path.exists(audio_dir):
                #     import glob
                #     bg_files = glob.glob(os.path.join(audio_dir, "bg_*.wav")) + glob.glob(os.path.join(audio_dir, "bg_*.mp3"))
                #     if bg_files:
                #         bg_audio = bg_files[0]
                #         print("⏳ Mezclando música de fondo...")
                #         mixed_output = output_path.replace(".mp4", "_mixed.mp4")
                #         from videocreator.infrastructure.engine.utils.audio_mixer import AudioMixer
                #         mixed_video_path = AudioMixer.mix_background_audio(
                #             video_path=output_path, audio_path=bg_audio, output_path=mixed_output, bg_volume=0.15
                #         )
                #         if os.path.exists(mixed_video_path):
                #             os.replace(mixed_video_path, output_path)
                #             print(f"✅ ¡Música integrada perfectamente!")
            except Exception as e:
                print(f"❌ Error al unir los clips: {e}")
            finally:
                if os.path.exists(concat_list_path):
                    os.remove(concat_list_path)
