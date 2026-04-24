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
            script_file = os.path.join(ep_dir, "script.json")
            meta_file = os.path.join(ep_dir, "metadata.json")
            
            if os.path.exists(script_file):  
                try:
                    with open(script_file, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                        
                    title = name
                    if os.path.exists(meta_file):
                        with open(meta_file, "r", encoding="utf-8") as f:
                            title = json.load(f).get("title", name)
                            
                    episodes.append({
                        "dir": ep_dir,
                        "name": name,
                        "title": title,
                        "script": script_data
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
                # Por convención el VeoProvider usa clip_01.mp4, clip_02.mp4
                expected_filename = f"clip_{scene_num:02d}.mp4"
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
        
        # Eliminar posible cache previo para forzar nueva voz
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        
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
        # El usuario ha pedido doblar EXPRESAMENTE final.mp4 en vez de clip por clip.
        ep_name = os.path.basename(ep_dir)
        final_mp4 = os.path.join(ep_dir, f"{ep_name}.mp4")
        if not os.path.exists(final_mp4):
            print(f"❌ No se encontró {ep_name}.mp4 en este episodio. Se necesita el vídeo completo para esta operación.")
            return

        character_name = scenes[0].get("character", "Narrator") if scenes else "Narrator"
        print(f"\n🚀 Iniciando doblaje global STS sobre: {os.path.basename(final_mp4)}")
        print(f"👉 Usaremos la voz del personaje: {character_name}")
        
        # 1. Extraer audio global
        veo_audio_path = AudioMixer.extract_audio(final_mp4)
        if not veo_audio_path:
            print(f"❌ No se pudo extraer audio de {os.path.basename(final_mp4)}.")
            return
            
        # 2. STS conversion sobre la pista global
        audio_filename = "dialogue_final_manual.wav"
        audio_dir = os.path.join(ep_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = os.path.join(audio_dir, audio_filename)
        
        # Eliminar posible cache previo para forzar nueva voz
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        
        print("🔄 Convertiendo voz en todo el vídeo con ElevenLabs...")
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
            print("❌ Falló el doblaje STS en el archivo completo.")
            return
            
        # 3. Mezclar el audio global convertido de vuelta al mp4
        ep_name = os.path.basename(ep_dir)
        mixed_path = os.path.join(ep_dir, f"{ep_name}_dubbed_manually.mp4")
        print("\n🎛️ Mezclando nueva pista doblada con el vídeo global...")
        final_clip_path = AudioMixer.mix_audio_to_video(
            video_path=final_mp4,
            audio_path=converted_audio,
            output_path=mixed_path,
            audio_volume=1.0
        )
        
        if final_clip_path:
            print(f"\n✅ ¡Doblaje completo exitoso! Tu vídeo final manual está en:")
            print(f"   -> {final_clip_path}")
        else:
            print("❌ Falló el inyectado de audio final.")
