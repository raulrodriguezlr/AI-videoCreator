"""Alternate-Ending engine — keep a clip's original head, regenerate the tail.

The user picks an exact cut second T. Everything before T stays the ORIGINAL
footage (no regeneration — perfect fidelity, free). The last frame at T seeds an
image-to-video continuation with a new-ending prompt. Head + continuation are
concatenated into the final clip.

This is image_to_video (i2v from the cut frame), NOT video_to_video: v2v would
re-render the whole clip and alter the original head. The i2v step is the only
paid call and is injected so the ffmpeg mechanism is fully testable offline.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Protocol

from videocreator.shared.errors import ValidationError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ])
    return float(out.strip())


def trim_head(src: Path, cut_at_s: float, out: Path) -> Path:
    """Original footage [0, cut_at_s]. Re-encoded so it ends EXACTLY at the cut
    (a stream-copy would snap to the previous keyframe and desync the seed frame)."""
    _run([
        "ffmpeg", "-y", "-i", str(src), "-t", f"{cut_at_s:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out),
    ])
    return out


def extract_seed_frame(head: Path, out_png: Path) -> Path:
    """The head's LAST frame — the exact image the continuation must start from."""
    _run([
        "ffmpeg", "-y", "-sseof", "-0.05", "-i", str(head),
        "-update", "1", "-frames:v", "1", str(out_png),
    ])
    return out_png


def concat(head: Path, tail: Path, out: Path) -> Path:
    """Join head + continuation into one continuous clip (re-encode for codec match)."""
    listf = out.parent / f"{out.stem}_concat.txt"
    # concat demuxer resolves relative paths against the list file's dir
    listf.write_text(
        f"file '{head.name}'\nfile '{tail.name}'\n", encoding="utf-8",
    )
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out),
    ])
    return out


class I2VContinuation(Protocol):
    """Generates the new-ending tail from the seed frame. The paid step."""

    def __call__(self, *, seed_frame: Path, prompt: str, duration_s: float, out: Path) -> Path: ...


class AlternateEndingService:
    def __init__(self, i2v: I2VContinuation, *, work_dir: Path) -> None:
        self._i2v = i2v
        self._work = work_dir

    def run(
        self,
        source: Path,
        *,
        cut_at_s: float,
        prompt: str,
        tail_duration_s: float = 5.0,
    ) -> Path:
        """Produce the alternate-ending clip. Synchronous (ffmpeg + i2v); callers
        wrap in asyncio.to_thread."""
        if not source.exists():
            raise FileNotFoundError(str(source))
        total = probe_duration(source)
        if cut_at_s <= 0 or cut_at_s >= total:
            raise ValidationError(
                f"cut ({cut_at_s}s) must be inside the clip (0, {total:.2f}s)"
            )
        if not prompt.strip():
            raise ValidationError("a new-ending prompt is required")

        self._work.mkdir(parents=True, exist_ok=True)
        head = trim_head(source, cut_at_s, self._work / "head.mp4")
        seed = extract_seed_frame(head, self._work / "seed.png")
        tail = self._i2v(
            seed_frame=seed, prompt=prompt, duration_s=tail_duration_s,
            out=self._work / "tail.mp4",
        )
        final = concat(head, tail, self._work / "alt_ending.mp4")
        log.info("alt_ending.done", cut_at_s=cut_at_s, out=str(final))
        return final


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-800:]}")


__all__ = [
    "AlternateEndingService",
    "I2VContinuation",
    "concat",
    "extract_seed_frame",
    "probe_duration",
    "trim_head",
]
