import os
import subprocess

class AudioMixer:
    """
    Utility class to mix generated audio (Lyria) with generated videos (Veo).
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
    def mix_audio_to_video(video_path: str, audio_path: str, output_path: str, audio_volume: float = 1.0) -> str:
        """
        Mixes an audio file into a video file.
        If the video already has audio (e.g., Veo 3.1 dialogue), the new audio is added as background 
        (mixed over the existing audio). If the video has no audio (e.g., Veo 2), the new audio
        becomes the main track.
        """
        if not AudioMixer.is_ffmpeg_installed():
            print("[MIXER] ❌ FFmpeg no está instalado o no está en el PATH del sistema.")
            return video_path
            
        print(f"[MIXER] 🎛️  Mezclando audio {os.path.basename(audio_path)} con vídeo {os.path.basename(video_path)}...")
        
        # We will use a complex filter graph to handle both cases:
        # 1. Video has audio: mix them together with amix.
        # 2. Video has no audio: just map the new audio track to it.
        #
        # FFmpeg command:
        # ffmpeg -i video.mp4 -i audio.wav -filter_complex "[0:a]volume=1.0[a0];[1:a]volume=0.5[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest output.mp4
        # Since we don't know easily beforehand if video has audio stream using pure python without ffprobe overhead,
        # we can attempt to mix. If it fails due to stream 0:a missing, we fallback to simple map.

        # First approach: Assume video has no audio (common for Veo 2 or if we just want to replace)
        # Using -c:v copy to avoid re-encoding the video, very fast.
        
        # To handle both safely: probe streams first.
        has_audio = AudioMixer._probe_has_audio(video_path)
        
        try:
            if has_audio:
                # Video has audio (e.g. Veo 3 character talking). We MIX the new audio underneath (ducking).
                # New audio volume is lowered so it doesn't overpower dialogue.
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex",
                    f"[0:a]volume=1.0[v_aud];[1:a]volume={audio_volume}[new_aud];[v_aud][new_aud]amix=inputs=2:duration=first:dropout_transition=2[a]",
                    "-map", "0:v",
                    "-map", "[a]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    output_path
                ]
            else:
                # Video is mute (Veo 2). Just map the audio track onto the video.
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex", f"[1:a]volume={audio_volume}[a]",
                    "-map", "0:v",
                    "-map", "[a]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    output_path
                ]
                
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if result.returncode == 0 and os.path.exists(output_path):
                print(f"[MIXER] ✅ Mezcla completada: {os.path.basename(output_path)}")
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
        except:
            return False
