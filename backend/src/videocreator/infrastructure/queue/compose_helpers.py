"""Pure helpers for the compose_short capability handler.

`collect_media_inputs` is pure (unit-tested); `compose_media` shells out to
FFmpeg: concat N clips, then mux the voiceover (if any) over the result,
keeping the shorter of the two streams.
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


def collect_media_inputs(upstream: dict[str, Any]) -> tuple[list[str], str | None]:
    """Pick video storage keys (in upstream insertion order) and one audio key.

    Upstream node results are dicts; videos expose `storage_key`, the tts
    handler exposes `audio_key`. Non-dict results are ignored.
    """
    videos: list[str] = []
    audio: str | None = None
    for value in upstream.values():
        if not isinstance(value, dict):
            continue
        vkey = value.get("storage_key")
        if isinstance(vkey, str) and vkey:
            videos.append(vkey)
        akey = value.get("audio_key")
        if audio is None and isinstance(akey, str) and akey:
            audio = akey
    return videos, audio


async def compose_media(
    videos: list[Path], audio: Path | None, out_path: Path,
) -> Path:
    """Concat clips (re-encode for safety) and optionally mux a voiceover."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_target = out_path if audio is None else out_path.with_suffix(".video.mp4")

    if len(videos) == 1 and audio is None:
        await _run_ffmpeg(["-i", str(videos[0]), "-c", "copy", str(out_path)])
        return out_path

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8",
        dir=str(out_path.parent),
    ) as f:
        for v in videos:
            f.write(f"file '{Path(v).as_posix()}'\n")
        list_path = f.name
    try:
        await _run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(concat_target),
        ])
    finally:
        Path(list_path).unlink(missing_ok=True)

    if audio is not None:
        await _run_ffmpeg([
            "-i", str(concat_target), "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ])
        concat_target.unlink(missing_ok=True)
    return out_path


async def _run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", *args]

    def run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(cmd, capture_output=True, check=False)

    proc = await asyncio.to_thread(run)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-400:]
        raise ProviderError(f"compose ffmpeg failed (exit {proc.returncode}): {tail}")


__all__ = ["collect_media_inputs", "compose_media"]
