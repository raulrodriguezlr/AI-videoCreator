import os
import subprocess


class AudioMixer:
    """
    Utility class to mix generated audio (ElevenLabs) with generated videos (Veo).
    Uses system FFmpeg through subprocess.
    """
    
    @staticmethod
    def is_ffmpeg_installed() -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def get_duration(file_path: str) -> float:
        """Get the duration of an audio or video file in seconds using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(result.stdout.strip())
        except (ValueError, Exception):
            return 0.0

    @staticmethod
    def mix_audio_to_video(video_path: str, audio_path: str, output_path: str, audio_volume: float = 1.0) -> str:
        """
        Mixes an audio file into a video file by COMPLETELY REPLACING the video's original audio.
        If the audio is shorter than the video, it pads the rest with silence.
        If the audio is longer than the video, it will stop when the video ends (optional, handled by ffmpeg defaults).
        """
        if not AudioMixer.is_ffmpeg_installed():
            print("[MIXER] ❌ FFmpeg no está instalado o no está en el PATH del sistema.")
            return video_path
            
        print(f"[MIXER] 🎛️  Reemplazando pista de audio con {os.path.basename(audio_path)}...")
        
        try:
            # -map 0:v (take video from input 0)
            # -map 1:a (take audio from input 1)
            # -c:v copy (don't re-encode video)
            # -c:a aac (encode audio to AAC)
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex", f"[1:a]volume={audio_volume}[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ]
                
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if result.returncode == 0 and os.path.exists(output_path):
                print(f"[MIXER] ✅ Audio reemplazado con éxito: {os.path.basename(output_path)}")
                return output_path
            else:
                print(f"[MIXER] ⚠️  Fallo en FFmpeg. Fallback al vídeo original. Log:\n{result.stderr}")
                return video_path
                
        except Exception as e:
            print(f"[MIXER] ❌ Error ejecutando FFmpeg: {e}")
            return video_path

    @staticmethod
    def mix_background_audio(video_path: str, audio_path: str, output_path: str, bg_volume: float = 0.3) -> str:
        """
        Mix background audio (music/SFX) UNDERNEATH the video's existing audio track.
        Unlike mix_audio_to_video which REPLACES the audio, this LAYERS the new audio
        at a lower volume while preserving the original dialogue.
        """
        if not AudioMixer.is_ffmpeg_installed():
            print("[MIXER] ❌ FFmpeg no está instalado.")
            return video_path

        has_audio = AudioMixer._probe_has_audio(video_path)
        print(f"[MIXER] 🎵 Mezclando música de fondo ({bg_volume:.0%} vol) bajo el diálogo...")

        try:
            if has_audio:
                # Video has dialogue → mix background underneath
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex",
                    f"[0:a]volume=1.0[dialogue];[1:a]volume={bg_volume}[bg];[dialogue][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                    "-map", "0:v",
                    "-map", "[a]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    output_path
                ]
            else:
                # Video has no dialogue → just add the background audio
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex", f"[1:a]volume={bg_volume}[a]",
                    "-map", "0:v",
                    "-map", "[a]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    output_path
                ]

            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if result.returncode == 0 and os.path.exists(output_path):
                print(f"[MIXER] ✅ Música de fondo mezclada: {os.path.basename(output_path)}")
                return output_path
            else:
                print(f"[MIXER] ⚠️  Fallo en FFmpeg. Fallback al vídeo original. Log:\n{result.stderr}")
                return video_path

        except Exception as e:
            print(f"[MIXER] ❌ Error ejecutando FFmpeg: {e}")
            return video_path

    @staticmethod
    def _probe_has_audio(video_path: str) -> bool:
        """Helper to quickly check if an MP4 has an audio stream."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a", 
            "-show_entries", "stream=codec_type", "-of", 
            "default=noprint_wrappers=1:nokey=1", video_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return "audio" in result.stdout.strip().lower()
        except Exception:
            return False
