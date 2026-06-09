import os
import subprocess
import re
from typing import Optional, Tuple

import structlog

log = structlog.get_logger(__name__)


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
            log.error("ffmpeg_not_installed")
            return video_path

        log.info("mixer_replacing_audio", audio=os.path.basename(audio_path))

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
                log.info("mixer_audio_replaced", output=os.path.basename(output_path))
                return output_path
            else:
                log.warning("mixer_ffmpeg_failed", stderr=result.stderr[:500])
                return video_path

        except Exception as e:
            log.error("mixer_ffmpeg_error", error=str(e))
            return video_path

    @staticmethod
    def mix_background_audio(video_path: str, audio_path: str, output_path: str, bg_volume: float = 0.3) -> str:
        """
        Mix background audio (music/SFX) UNDERNEATH the video's existing audio track.
        Unlike mix_audio_to_video which REPLACES the audio, this LAYERS the new audio
        at a lower volume while preserving the original dialogue.
        """
        if not AudioMixer.is_ffmpeg_installed():
            log.error("ffmpeg_not_installed")
            return video_path

        has_audio = AudioMixer._probe_has_audio(video_path)
        log.info("mixer_bg_audio_mixing", volume=f"{bg_volume:.0%}")

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
                log.info("mixer_bg_audio_mixed", output=os.path.basename(output_path))
                return output_path
            else:
                log.warning("mixer_ffmpeg_failed", stderr=result.stderr[:500])
                return video_path

        except Exception as e:
            log.error("mixer_ffmpeg_error", error=str(e))
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

    # ==========================================
    # AUDIO SYNC PIPELINE METHODS
    # ==========================================

    @staticmethod
    def extract_audio(video_path: str, output_path: str = None) -> str:
        """
        Extract the audio track from a video file to WAV.

        Args:
            video_path: Path to the video file.
            output_path: Optional output path. Defaults to <video>_audio.wav.

        Returns:
            Path to the extracted WAV file, or empty string on failure.
        """
        if not output_path:
            output_path = video_path.replace(".mp4", "_veo_audio.wav")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",               # no video
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "1",          # mono for analysis
            output_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0 and os.path.exists(output_path):
                log.info("sync_audio_extracted", output=os.path.basename(output_path))
                return output_path
            else:
                log.warning("sync_audio_extract_failed", stderr=result.stderr[:200])
                return ""
        except Exception as e:
            log.error("sync_audio_extract_error", error=str(e))
            return ""

    @staticmethod
    def detect_speech_duration(audio_path: str, silence_threshold: str = "-30dB", min_silence_dur: float = 0.5) -> tuple:
        """
        Detect where speech starts and ends in an audio file using ffmpeg silencedetect.

        Returns:
            (speech_start, speech_end, speech_duration) in seconds.
            Falls back to (0, total_duration, total_duration) if detection fails.
        """
        total_duration = AudioMixer.get_duration(audio_path)
        if total_duration <= 0:
            return (0.0, 0.0, 0.0)

        # Run silencedetect to find silent regions
        cmd = [
            "ffmpeg", "-i", audio_path,
            "-af", f"silencedetect=noise={silence_threshold}:d={min_silence_dur}",
            "-f", "null", "-"
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stderr = result.stderr

            # Parse silence_start and silence_end from ffmpeg output
            silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", stderr)]
            silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", stderr)]

            if not silence_starts and not silence_ends:
                # No silence detected — entire clip is speech
                log.debug("sync_no_silence_detected", duration_s=round(total_duration, 2))
                return (0.0, total_duration, total_duration)

            # Speech starts = end of the first leading silence (or 0 if no leading silence)
            speech_start = 0.0
            if silence_starts and silence_starts[0] < 0.1:
                # There's silence at the beginning
                if silence_ends:
                    speech_start = silence_ends[0]

            # Speech ends = start of the last trailing silence (or total_duration)
            speech_end = total_duration
            if silence_starts and silence_starts[-1] > total_duration * 0.7:
                # There's silence at the end
                speech_end = silence_starts[-1]

            speech_duration = max(0.0, speech_end - speech_start)
            log.debug(
                "sync_speech_detected",
                start_s=round(speech_start, 2),
                end_s=round(speech_end, 2),
                speech_s=round(speech_duration, 2),
                total_s=round(total_duration, 2),
            )
            return (speech_start, speech_end, speech_duration)

        except Exception as e:
            log.warning("sync_silencedetect_error", error=str(e))
            return (0.0, total_duration, total_duration)

    @staticmethod
    def time_stretch_audio(audio_path: str, target_duration: float, speech_start_offset: float = 0.0) -> str:
        """
        Time-stretch audio to match a target duration, and optionally pad
        with silence at the start to align with the speech start offset.

        Uses ffmpeg atempo filter (supports 0.5x–100x via chaining).

        Args:
            audio_path: Path to the source audio (ElevenLabs TTS).
            target_duration: Desired speech duration in seconds.
            speech_start_offset: Seconds of silence to prepend.

        Returns:
            Path to the synced audio file.
        """
        source_duration = AudioMixer.get_duration(audio_path)
        if source_duration <= 0 or target_duration <= 0:
            log.warning("sync_invalid_duration", source_s=source_duration, target_s=target_duration)
            return audio_path

        # Calculate speed factor: >1 means speed up, <1 means slow down
        speed_factor = source_duration / target_duration

        # Clamp to reasonable bounds (0.5x to 2.0x)
        speed_factor = max(0.5, min(speed_factor, 2.0))

        output_path = audio_path.replace(".wav", "_synced.wav").replace(".mp3", "_synced.wav")

        log.info(
            "sync_time_stretch",
            source_s=round(source_duration, 2),
            target_s=round(target_duration, 2),
            factor=round(speed_factor, 3),
        )

        try:
            # Build atempo filter chain (atempo supports 0.5 to 100.0 per instance)
            # For factors outside 0.5-2.0 we'd chain, but we've clamped above
            atempo_filter = f"atempo={speed_factor}"

            if speech_start_offset > 0.01:
                # Generate silence + concatenate with stretched audio
                silence_path = audio_path.replace(".wav", "_silence.wav").replace(".mp3", "_silence.wav")
                stretched_path = audio_path.replace(".wav", "_stretched.wav").replace(".mp3", "_stretched.wav")

                # Step 1: Generate silence
                silence_cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
                    "-t", str(speech_start_offset),
                    "-acodec", "pcm_s16le",
                    silence_path
                ]
                subprocess.run(silence_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                # Step 2: Stretch the TTS audio
                stretch_cmd = [
                    "ffmpeg", "-y",
                    "-i", audio_path,
                    "-filter:a", atempo_filter,
                    "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
                    stretched_path
                ]
                subprocess.run(stretch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                # Step 3: Concatenate silence + stretched audio
                concat_list_path = audio_path.replace(".wav", "_concat.txt").replace(".mp3", "_concat.txt")
                with open(concat_list_path, "w") as f:
                    f.write(f"file '{silence_path}'\n")
                    f.write(f"file '{stretched_path}'\n")

                concat_cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_list_path,
                    "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
                    output_path
                ]
                result = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                # Cleanup temp files
                for tmp in [silence_path, stretched_path, concat_list_path]:
                    if os.path.exists(tmp):
                        os.remove(tmp)
            else:
                # No offset needed — just stretch
                cmd = [
                    "ffmpeg", "-y",
                    "-i", audio_path,
                    "-filter:a", atempo_filter,
                    "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
                    output_path
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if os.path.exists(output_path):
                final_dur = AudioMixer.get_duration(output_path)
                log.info(
                    "sync_audio_synced",
                    duration_s=round(final_dur, 2),
                    target_s=round(target_duration, 2),
                    offset_s=round(speech_start_offset, 2),
                )
                return output_path
            else:
                log.warning("sync_time_stretch_failed")
                return audio_path

        except Exception as e:
            log.error("sync_time_stretch_error", error=str(e))
            return audio_path
