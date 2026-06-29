"""Source-clip ingestion for the Alternate-Ending feature.

Two ways in:
- a dragged-and-dropped local mp4 (bytes saved straight to the work area), and
- a YouTube URL fetched with yt-dlp.

yt-dlp is a lazy import so the module loads without it; downloading third-party
video carries copyright/ToS weight, so the YouTube path is meant to sit behind
the fair-use advisor at the call site (`require_rights_ack`).
"""
from __future__ import annotations

import re
from pathlib import Path

from videocreator.shared.errors import ProviderError, ValidationError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_YT_RE = re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB guard


def is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.match(url.strip()))


def save_upload(data: bytes, dest: Path, *, filename: str = "source.mp4") -> Path:
    """Persist a drag-and-dropped clip. Validates size + extension."""
    if not data:
        raise ValidationError("empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValidationError(f"file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not filename.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        raise ValidationError("unsupported file type — use mp4/mov/webm/mkv")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "source.mp4"
    out.write_bytes(data)
    log.info("ingest.upload.saved", bytes=len(data), out=str(out))
    return out


def ingest_youtube(url: str, dest: Path, *, require_rights_ack: bool = True, rights_ack: bool = False) -> Path:
    """Download a YouTube video to dest/source.mp4 via yt-dlp.

    `require_rights_ack` enforces an explicit acknowledgement that the user has
    the rights / a fair-use basis before any third-party download happens.
    """
    if not is_youtube_url(url):
        raise ValidationError("not a YouTube URL")
    if require_rights_ack and not rights_ack:
        raise ValidationError(
            "downloading third-party video requires confirming you have the "
            "rights or a fair-use basis"
        )
    try:
        import yt_dlp  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - dep guard
        raise ProviderError("yt-dlp not installed — pip install yt-dlp") from e

    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "source.mp4"
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best",
        "outtmpl": str(dest / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
    }
    try:  # pragma: no cover - network
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:  # pragma: no cover - network
        raise ProviderError(f"YouTube download failed: {e}") from e
    if not out.exists():
        # yt-dlp may have written a non-mp4 container; pick whatever landed.
        produced = next((p for p in dest.glob("source.*") if p.suffix != ".txt"), None)
        if produced is None:
            raise ProviderError("YouTube download produced no file")
        produced.rename(out)
    log.info("ingest.youtube.done", url=url, out=str(out))
    return out


__all__ = ["ingest_youtube", "is_youtube_url", "save_upload"]
