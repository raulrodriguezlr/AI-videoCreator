import os
import json
import subprocess
from typing import List, Optional

from src.providers.elevenlabs_provider import ElevenLabsProvider
from src.utils.audio_mixer import AudioMixer

class ManualDubber:
    """
    Gestor interactivo para aplicar doblaje STS a clips generados
    previamente sin necesidad de re-generar el vídeo con Veo.
    """
    def __init__(self, pod_name: str, pod_config_path: str, episode_mgr):
        self.pod_name = pod_name
        self.pod_config_path = pod_config_path
        self.episode_mgr = episode_mgr
        self.eleven_prov = ElevenLabsProvider(pod_config_path)

    def run_interactive(self):
        print("\n🎙️ --- Doblaje Manual (STS) --- 🎙️")
        
        # 1. Seleccionar episodio
        episodes = []
        pod_output_dir = os.path.join("pods", self.pod_name, "output")
        if not os.path.exists(pod_output_dir):
            print("❌ No hay episodios generados.")
            return

        for name in sorted(os.listdir(pod_output_dir)):
            ep_dir = os.path.join(pod_output_dir, name)
            if not os.path.isdir(ep_dir) or not name.startswith("ep_"):
                continue
            progress_file = os.path.join(ep_dir, "progress.json")
            if os.path.exists(progress_file):  
                try:
                    with open(progress_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    episodes.append({
                        "dir": ep_dir,
                        "name": name,
                        "title": data.get("title", name),
                        "script": data.get("script", {})
                    })
                except Exception:
                    continue

        if not episodes:
            print("❌ No hay episodios válidos.")
            return

        print("\nEpisodios disponibles:")
        for idx, ep in enumerate(episodes, 1):
            print(f"  {idx}. {ep['title']} ({ep['name']})")
            
        try:
            ep_sel = int(input(f"\nSelecciona un episodio para doblar (1-{len(episodes)}): ")) - 1
            if ep_sel < 0 or ep_sel >= len(episodes):
                print("❌ Selección fuera de rango.")
                return
        except ValueError:
            print("❌ Entrada inválida.")
            return

        chosen_ep = episodes[ep_sel]
        ep_dir = chosen_ep["dir"]
        script = chosen_ep["script"]
        scenes = script.get("scenes", [])
        
        if not scenes:
            print("❌ El episodio no tiene script guardado o no tiene escenas.")
            return

        clips_dir = os.path.join(ep_dir, "clips")
        if not os.path.exists(clips_dir):
            print("❌ No se encontró la carpeta de clips para este episodio.")
            return

        # Listar clips disponibles (Nativos)
        # Asumimos archivos mp4 que no terminan en _dubbed.mp4 ni _dubbed_manually.mp4
        available_clips = []
        for f in sorted(os.listdir(clips_dir)):
            if f.endswith(".mp4") and not "_dubbed" in f:
                available_clips.append(os.path.join(clips_dir, f))

        if not available_clips:
            print("⚠️ No se encontraron clips nativos sin doblar.")
            return

        print("\n🎬 Clips Nativos Disponibles:")
        for clip_path in available_clips:
            print(f"  - {os.path.basename(clip_path)}")
            
        print(f"\nEl episodio tiene un máximo de {len(scenes)} escenas registradas en el guion.")
        
        choice = input("\nIntroduce el número de escena (ej: 01, 1, 2) o escribe 'all'/'todos' para doblar todos en secuencia: ").strip().lower()

        if choice in ["all", "todos"]:
            self._dub_all_clips(available_clips, scenes, ep_dir, clips_dir)
        else:
            try:
                scene_num = int(choice)
                if scene_num < 1 or scene_num > len(scenes):
                    print(f"❌ Número de escena ({scene_num}) está fuera del rango válido (1 - {len(scenes)}).")
                    return
                
                # Buscar el clip que corresponde a esta escena
                # Por convención el VeoProvider usa scene_01.mp4, scene_02.mp4
                expected_filename = f"scene_{scene_num:02d}.mp4"
                target_clip_path = os.path.join(clips_dir, expected_filename)
                
                if target_clip_path not in available_clips:
                    print(f"❌ El clip {expected_filename} no se encuentra entre los clips generados.")
                    return
                    
                self._dub_single_clip(target_clip_path, scenes[scene_num - 1], clips_dir, scene_num)
                
            except ValueError:
                print("❌ Input inválido. Debes poner un número o 'all'.")

    def _dub_single_clip(self, clip_path: str, scene_data: dict, clips_dir: str, scene_num: int) -> Optional[str]:
        audio_text = scene_data.get("audio_text", "")
        character_name = scene_data.get("character", "")
        
        if not audio_text or not character_name:
            print(f"⚠️ La escena {scene_num} no tiene diálogo asignado en el guion. Ignorando doblaje.")
            return None

        print(f"\n🎙️ Doblando manualmente escena {scene_num} ({os.path.basename(clip_path)})")
        print(f"   Personaje: {character_name}")
        
        # 1. Extraer audio
        veo_audio_path = AudioMixer.extract_audio(clip_path)
        if not veo_audio_path:
            print("❌ No se pudo extraer audio nativo.")
            return None
            
        # 2. STS Convert
        scene_num_str = f"{scene_num:02d}"
        audio_filename = f"dialogue_manual_{scene_num_str}.wav"
        audio_path = os.path.join(clips_dir, audio_filename)
        
        converted_audio = self.eleven_prov.convert_voice(
            source_audio_path=veo_audio_path,
            character_name=character_name,
            output_path=audio_path
        )
        
        try:
            os.remove(veo_audio_path)
        except OSError:
            pass
            
        if not converted_audio:
            print("❌ Falló STS y no aplicaremos TTS como fallback en modo manual para forzar la revisión.")
            return None
            
        # 3. Mix
        mixed_path = clip_path.replace(".mp4", "_dubbed_manually.mp4")
        final_clip_path = AudioMixer.mix_audio_to_video(
            video_path=clip_path,
            audio_path=converted_audio,
            output_path=mixed_path,
            audio_volume=1.0
        )
        
        if final_clip_path:
            print(f"✅ Clip doblado resultante: {os.path.basename(final_clip_path)}")
            return final_clip_path
        else:
            print("❌ Falló el inyectado de audio final.")
            return None

    def _dub_all_clips(self, available_clips: List[str], scenes: List[dict], ep_dir: str, clips_dir: str):
        print(f"\n🚀 Iniciando doblaje masivo de {len(available_clips)} clips...")
        
        dubbed_paths = []
        
        # We need to process them in expected sequential order to concat them later
        for scene_num in range(1, len(scenes) + 1):
            expected_filename = f"scene_{scene_num:02d}.mp4"
            target_clip_path = os.path.join(clips_dir, expected_filename)
            
            if target_clip_path in available_clips:
                res = self._dub_single_clip(target_clip_path, scenes[scene_num - 1], clips_dir, scene_num)
                # Fallback to native path if dubbing failed or scene has no dialogue
                dubbed_paths.append(res if res else target_clip_path)
            else:
                # Clip missing from available? Maybe it failed generation originally or was already dubbed
                # Let's see if a dubbed version exists from auto pipeline
                auto_dubbed = target_clip_path.replace(".mp4", "_dubbed.mp4")
                if os.path.exists(auto_dubbed):
                    dubbed_paths.append(auto_dubbed)
                elif os.path.exists(target_clip_path):
                    dubbed_paths.append(target_clip_path)
                else:
                    print(f"⚠️ Escena {scene_num} saltada por archivo faltante.")
        
        if not dubbed_paths:
            print("❌ No se generaron rutas válidas para concatenar.")
            return
            
        # Concat final video
        final_dubbed_manually = os.path.join(ep_dir, "final_dubbed_manually.mp4")
        print(f"\n🎬 Concatenando {len(dubbed_paths)} clips en {final_dubbed_manually}...")
        
        concat_list_path = os.path.join(clips_dir, "_manual_concat_list.txt")
        try:
            with open(concat_list_path, "w") as f:
                for p in dubbed_paths:
                    safe_path = p.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    final_dubbed_manually,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"✅ ¡Concatenación exitosa! Tu vídeo final está en: {final_dubbed_manually}")
            else:
                print(f"❌ ffmpeg concat error: {result.stderr[:200]}")
                
            os.remove(concat_list_path)
        except Exception as e:
            print(f"❌ Error al concatenar: {e}")
