"""
audio_separator.py — Separación de voz y efectos de sonido usando Demucs (Meta).

Demucs separa una pista de audio en componentes individuales:
  - vocals: voz humana/personaje aislada
  - no_vocals: todo lo demás (efectos de sonido, ambiente, música)

Esto permite doblar SOLO la voz con ElevenLabs STS y luego
mezclarla de vuelta con los efectos originales de Veo.
"""

import os
import sys
import subprocess
import shutil
from typing import Optional, Tuple

import structlog

log = structlog.get_logger(__name__)


class AudioSeparator:
    """
    Separa audio en voz y efectos usando Demucs (htdemucs).

    Flujo:
        audio_veo.wav → Demucs → vocals.wav + no_vocals.wav
    """

    # Demucs model to use. htdemucs is the fastest and good enough for voice isolation.
    MODEL = "htdemucs"

    @staticmethod
    def is_available() -> bool:
        """Check if Demucs is installed and accessible."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "demucs", "--help"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def separate(
        audio_path: str,
        output_dir: str = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Separate an audio file into vocals and non-vocals (SFX/ambient).

        Args:
            audio_path: Path to the source audio file (WAV or MP3).
            output_dir: Directory to store separated tracks.
                        Defaults to same dir as audio_path.

        Returns:
            Tuple of (vocals_path, no_vocals_path) on success, None on failure.
        """
        if not os.path.exists(audio_path):
            log.error("demucs_audio_not_found", path=audio_path)
            return None

        if output_dir is None:
            output_dir = os.path.dirname(audio_path)

        # Create a temp output directory for Demucs
        demucs_out = os.path.join(output_dir, "_demucs_temp")
        os.makedirs(demucs_out, exist_ok=True)

        try:
            log.info("demucs_separating", audio=os.path.basename(audio_path))

            # --two-stems vocals: only separate into vocals + no_vocals (fastest)
            # -n htdemucs: use the hybrid transformer model
            cmd = [
                sys.executable, "-m", "demucs",
                "--two-stems", "vocals",
                "-n", AudioSeparator.MODEL,
                "-o", demucs_out,
                audio_path
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120  # 2 min max per clip
            )

            if result.returncode != 0:
                log.error("demucs_separation_failed", returncode=result.returncode)
                return None

            # Demucs outputs to: <output_dir>/htdemucs/<filename_without_ext>/vocals.wav + no_vocals.wav
            audio_basename = os.path.splitext(os.path.basename(audio_path))[0]
            separated_dir = os.path.join(demucs_out, AudioSeparator.MODEL, audio_basename)

            vocals_src = os.path.join(separated_dir, "vocals.wav")
            no_vocals_src = os.path.join(separated_dir, "no_vocals.wav")

            if not os.path.exists(vocals_src) or not os.path.exists(no_vocals_src):
                log.error("demucs_output_not_found", dir=separated_dir)
                return None

            # Move results to the output directory with clear names
            vocals_dst = os.path.join(output_dir, f"{audio_basename}_vocals.wav")
            no_vocals_dst = os.path.join(output_dir, f"{audio_basename}_sfx.wav")

            shutil.move(vocals_src, vocals_dst)
            shutil.move(no_vocals_src, no_vocals_dst)

            log.info(
                "demucs_separated",
                vocals=os.path.basename(vocals_dst),
                sfx=os.path.basename(no_vocals_dst),
            )
            return (vocals_dst, no_vocals_dst)

        except subprocess.TimeoutExpired:
            log.error("demucs_timeout")
            return None
        except Exception as e:
            log.error("demucs_unexpected_error", error=str(e))
            return None
        finally:
            # Cleanup temp Demucs directory
            try:
                shutil.rmtree(demucs_out, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def remix_voice_with_sfx(
        dubbed_voice_path: str,
        sfx_path: str,
        output_path: str,
        voice_volume: float = 1.0,
        sfx_volume: float = 0.7,
    ) -> Optional[str]:
        """
        Mix the dubbed voice track back with the original sound effects.

        Args:
            dubbed_voice_path: Path to the ElevenLabs-converted voice.
            sfx_path: Path to the isolated sound effects from Demucs.
            output_path: Path for the final mixed audio.
            voice_volume: Volume multiplier for the dubbed voice (default 1.0).
            sfx_volume: Volume multiplier for the SFX layer (default 0.7).

        Returns:
            Path to the mixed audio file, or None on failure.
        """
        if not os.path.exists(dubbed_voice_path) or not os.path.exists(sfx_path):
            log.error("remix_missing_inputs", voice=dubbed_voice_path, sfx=sfx_path)
            return None

        try:
            log.info("remix_mixing", voice=os.path.basename(dubbed_voice_path), sfx=os.path.basename(sfx_path))

            # Use ffmpeg amix to layer voice on top of SFX
            cmd = [
                "ffmpeg", "-y",
                "-i", dubbed_voice_path,
                "-i", sfx_path,
                "-filter_complex",
                f"[0:a]volume={voice_volume}[voice];"
                f"[1:a]volume={sfx_volume}[sfx];"
                f"[voice][sfx]amix=inputs=2:duration=longest:dropout_transition=2[out]",
                "-map", "[out]",
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "1",
                output_path
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )

            if result.returncode == 0 and os.path.exists(output_path):
                log.info("remix_done", output=os.path.basename(output_path))
                return output_path
            else:
                log.error("remix_ffmpeg_failed", stderr=result.stderr[:200])
                return None

        except Exception as e:
            log.error("remix_unexpected_error", error=str(e))
            return None
