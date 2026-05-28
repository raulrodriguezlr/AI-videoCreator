import os
import subprocess
from typing import List

from src.utils.episode_manager import EpisodeManager


class VideoEditor:
    """
    Herramienta interactiva para seleccionar clips específicos de un episodio
    y unirlos en un único vídeo final.
    """

    def __init__(self, pod_name: str, pod_config_path: str):
        self.pod_name = pod_name
        self.pod_config_path = pod_config_path
        self.pod_output_dir = os.path.join("pods", pod_name, "output")

    def _get_video_info(self, file_path: str) -> str:
        """Extracts critical video stream info to compare encoding DNA."""
        cmd = [
            "ffprobe", "-v", "error", 
            "-show_entries", "stream=codec_name,r_frame_rate,width,height,channels,sample_rate", 
            "-of", "csv=p=0", file_path
        ]
        try:
            return subprocess.check_output(cmd, text=True).strip()
        except:
            return ""

    def _normalize_clips(self, clips: List[str]) -> List[str]:
        """Ensures all clips have the same format as the first clip to prevent frozen concatenation."""
        if not clips: return []
        
        print("\n🔍 Comprobando el ADN (formato) de los clips...")
        base_info = self._get_video_info(clips[0])
        normalized_clips = []
        
        for clip in clips:
            info = self._get_video_info(clip)
            if info != base_info and info != "":
                print(f"  ⚠️  El clip '{os.path.basename(clip)}' tiene un formato distinto. Estandarizando (puede tardar un poco)...")
                fixed_path = clip.replace(".mp4", "_normalized.mp4")
                
                # Force to standard Veo format (24fps, yuv420p, 44.1kHz Mono AAC)
                cmd = [
                    "ffmpeg", "-y", "-i", clip, 
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
                    "-c:a", "aac", "-ar", "44100", "-ac", "1",
                    fixed_path
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                normalized_clips.append(fixed_path)
            else:
                normalized_clips.append(clip)
                
        return normalized_clips

    def run_interactive(self):
        print(f"\n{'='*60}")
        print(f"✂️  EDITOR DE VÍDEO — Unir clips personalizados")
        print(f"{'='*60}")

        if not os.path.exists(self.pod_output_dir):
            print(f"❌ No se encontró la carpeta de salida para el pod '{self.pod_name}'.")
            return

        # 1. Listar episodios disponibles
        episodes = []
        for name in sorted(os.listdir(self.pod_output_dir)):
            ep_dir = os.path.join(self.pod_output_dir, name)
            if os.path.isdir(ep_dir) and name.startswith("ep_"):
                episodes.append({"name": name, "dir": ep_dir})

        if not episodes:
            print("❌ No hay episodios generados todavía.")
            return

        print("\n📂 Episodios disponibles:")
        for idx, ep in enumerate(episodes, 1):
            print(f"  {idx}. {ep['name']}")

        pick = input(f"\nElige el episodio a editar (1-{len(episodes)}): ").strip()
        if not pick.isdigit() or not (1 <= int(pick) <= len(episodes)):
            print("❌ Selección no válida.")
            return

        chosen_ep = episodes[int(pick) - 1]
        ep_dir = chosen_ep["dir"]
        ep_name = chosen_ep["name"]
        clips_dir = os.path.join(ep_dir, "clips")

        if not os.path.exists(clips_dir):
            print(f"❌ La carpeta 'clips' no existe en {ep_name}.")
            return

        # 2. Listar clips disponibles
        all_files = sorted(os.listdir(clips_dir))
        
        # Agrupar por número base. Un número puede tener versión normal y '_dubbed'
        clip_bases = set()
        for f in all_files:
            if f.endswith(".mp4") and f.startswith("clip_"):
                # extraemos número "clip_01" -> "01" o "clip_01_dubbed" -> "01"
                base_num = f.replace("clip_", "").replace("_dubbed.mp4", "").replace(".mp4", "")
                if base_num.isdigit():
                    clip_bases.add(int(base_num))

        if not clip_bases:
            print(f"❌ No se encontraron clips válidos en {ep_name}/clips/")
            return

        sorted_bases = sorted(list(clip_bases))
        print(f"\n🎞️  Clips disponibles en {ep_name}:")
        
        available_clips_info = {}
        for num in sorted_bases:
            num_str = f"{num:02d}"
            dubbed = f"clip_{num_str}_dubbed.mp4"
            native = f"clip_{num_str}.mp4"
            
            if dubbed in all_files:
                path = os.path.join(clips_dir, dubbed)
            elif native in all_files:
                path = os.path.join(clips_dir, native)
            else:
                continue
                
            available_clips_info[num] = path
            print(f"  Clip {num}")

        # 3. Pedir al usuario qué clips unir
        print("\n📝 ¿Qué clips quieres unir?")
        print("  - Escribe 'entero' para unir TODOS los clips listados en orden.")
        print("  - Escribe números separados por comas para elegir y ordenar a medida (ej: 1,2,3,4,7,8)")
        selection = input("> ").strip().lower()

        clips_to_join = []
        if selection == "entero":
            for num in sorted_bases:
                if num in available_clips_info:
                    clips_to_join.append(available_clips_info[num])
        else:
            parts = selection.split(",")
            for p in parts:
                p = p.strip()
                if p.isdigit():
                    num = int(p)
                    if num in available_clips_info:
                        clips_to_join.append(available_clips_info[num])
                    else:
                        print(f"⚠️  Advertencia: Clip {num} no existe, ignorando...")

        if not clips_to_join:
            print("❌ No se ha seleccionado ningún clip válido. Cancelando.")
            return

        # 4. Nombre del archivo de salida
        default_name = f"{ep_name}_dubbed.mp4"
        out_name = input(f"\n💾 Nombre del archivo final (Por defecto: '{default_name}'): ").strip()
        if not out_name:
            out_name = default_name
        if not out_name.endswith(".mp4"):
            out_name += ".mp4"

        output_path = os.path.join(ep_dir, out_name)

        # 5. Estandarizar clips editados manualmente (si los hay)
        clips_to_join = self._normalize_clips(clips_to_join)

        # 6. Concatenar usando ffmpeg
        print(f"\n🔄 Preparando para unir {len(clips_to_join)} clips...")
        
        concat_list_path = os.path.join(ep_dir, "_editor_concat_list.txt")
        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for cp in clips_to_join:
                    abs_path = os.path.abspath(cp).replace("\\", "/")
                    f.write(f"file '{abs_path}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                output_path
            ]
            
            print(f"⏳ Ejecutando FFmpeg...")
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            print(f"✅ ¡Éxito! Vídeo final guardado en:\n  -> {output_path}")

            # --- BACKGROUND AUDIO DISABLED ---
            # 7. Buscar música de fondo (background audio)
            # audio_dir = os.path.join(ep_dir, "audio")
            # if os.path.exists(audio_dir):
            #     import glob
            #     bg_files = glob.glob(os.path.join(audio_dir, "bg_*.wav")) + glob.glob(os.path.join(audio_dir, "bg_*.mp3"))
            #     if bg_files:
            #         bg_audio = bg_files[0]
            #         print(f"\n🎵 Se ha detectado música de fondo: {os.path.basename(bg_audio)}")
            #         ans = input("¿Deseas añadirla al vídeo final? (S/n): ").strip().lower()
            #         if ans != 'n':
            #             from src.utils.audio_mixer import AudioMixer
            #             print("⏳ Mezclando música de fondo...")
            #             mixed_output = output_path.replace(".mp4", "_mixed.mp4")
            #             mixed_video_path = AudioMixer.mix_background_audio(
            #                 video_path=output_path,
            #                 audio_path=bg_audio,
            #                 output_path=mixed_output,
            #                 bg_volume=0.15
            #             )
            #             if os.path.exists(mixed_video_path) and mixed_video_path != output_path:
            #                 try:
            #                     os.replace(mixed_video_path, output_path)
            #                     print(f"✅ ¡Música integrada perfectamente!")
            #                 except OSError as e:
            #                     print(f"⚠️  Error renombrando el archivo mezclado: {e}")

        except subprocess.CalledProcessError:
            print("❌ Error al unir los clips con FFmpeg. Asegúrate de que todos los clips tengan el mismo formato, resolución y framerate.")
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
        finally:
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except:
                    pass

