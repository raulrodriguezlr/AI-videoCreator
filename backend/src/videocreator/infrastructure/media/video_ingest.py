"""Video download and frame extraction for the Video Analyst.

Downloads videos from URLs via yt-dlp, extracts frames for analysis.
"""
from __future__ import annotations

from pathlib import Path

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


def download_video(url: str, out_dir: Path) -> Path:
    """Download video from URL using yt-dlp. Returns path to downloaded file."""
    import yt_dlp  # type: ignore[import-untyped]

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "mp4[height<=1080]/best[height<=1080]/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "max_filesize": MAX_FILE_SIZE,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


def extract_frames(video_path: Path, out_dir: Path, *, fps: int = 1) -> list[Path]:
    """Extract frames from video at given fps using ffmpeg."""
    import subprocess

    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "f_%04d.png")
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        pattern,
        "-y", "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    frames = sorted(out_dir.glob("f_*.png"))
    log.info("video_ingest.frames_extracted", count=len(frames), video=video_path.name)
    return frames


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    """Extract audio track as WAV for transcription/beat analysis."""
    import subprocess

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.wav"
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn", "-ar", "22050", "-ac", "1",
        str(audio_path),
        "-y", "-loglevel", "error",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return audio_path


__all__ = ["download_video", "extract_audio", "extract_frames"]
