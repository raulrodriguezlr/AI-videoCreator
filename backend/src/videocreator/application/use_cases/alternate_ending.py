"""Alternate-Ending engine — keep a clip's original head, change the ending.

The user picks an exact cut second T. Everything before T stays the ORIGINAL
footage (no regeneration — perfect fidelity, free). Two modes produce the new
ending:

  * `mode="i2v"` (default, unchanged behaviour): the head's LAST frame seeds an
    image-to-video continuation with a new-ending prompt — a from-scratch
    regeneration, so only the *idea* of the original tail survives.
  * `mode="edit"`: the REAL tail footage [T, T+tail_duration_s] is cut out and
    handed to a video_to_video EDITING model (e.g. Gemini Omni Flash) that
    keeps the original motion/actors and applies the prompt as an edit —
    "editar el vídeo real" instead of regenerating it from a still.

Head + (i2v or edited) tail are concatenated into the final clip either way.
The i2v/v2v step is the only paid call and is injected so the ffmpeg mechanism
is fully testable offline (see test_alternate_ending.py).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, Protocol

from videocreator.shared.errors import ValidationError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

AlternateEndingMode = Literal["i2v", "edit"]


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
    """The head's LAST frame — the exact image an i2v continuation must start from."""
    _run([
        "ffmpeg", "-y", "-sseof", "-0.05", "-i", str(head),
        "-update", "1", "-frames:v", "1", str(out_png),
    ])
    return out_png


def extract_tail(src: Path, cut_at_s: float, tail_duration_s: float, out: Path) -> Path:
    """The REAL footage [cut_at_s, cut_at_s + tail_duration_s] — the base clip
    `mode="edit"` hands to a video_to_video model, instead of discarding it for
    an i2v regeneration from a single still frame."""
    _run([
        "ffmpeg", "-y", "-ss", f"{cut_at_s:.3f}", "-i", str(src),
        "-t", f"{tail_duration_s:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out),
    ])
    return out


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
    """Generates the new-ending tail from the seed frame. The paid step for `mode="i2v"`."""

    def __call__(self, *, seed_frame: Path, prompt: str, duration_s: float, out: Path) -> Path: ...


class V2VContinuation(Protocol):
    """Edits the real tail clip into the new ending. The paid step for `mode="edit"`."""

    def __call__(self, *, video: Path, prompt: str, duration_s: float, out: Path) -> Path: ...


class AlternateEndingService:
    def __init__(
        self, i2v: I2VContinuation, *, work_dir: Path, v2v: V2VContinuation | None = None,
    ) -> None:
        self._i2v = i2v
        self._v2v = v2v
        self._work = work_dir

    def run(
        self,
        source: Path,
        *,
        cut_at_s: float,
        prompt: str,
        tail_duration_s: float = 5.0,
        mode: AlternateEndingMode = "i2v",
    ) -> Path:
        """Produce the alternate-ending clip. Synchronous (ffmpeg + i2v/v2v);
        callers wrap in asyncio.to_thread."""
        if not source.exists():
            raise FileNotFoundError(str(source))
        total = probe_duration(source)
        if cut_at_s <= 0 or cut_at_s >= total:
            raise ValidationError(
                f"cut ({cut_at_s}s) must be inside the clip (0, {total:.2f}s)"
            )
        if not prompt.strip():
            raise ValidationError("a new-ending prompt is required")
        if mode not in ("i2v", "edit"):
            raise ValidationError(f"unknown mode '{mode}' — expected 'i2v' or 'edit'")
        if mode == "edit" and self._v2v is None:
            raise ValidationError("mode='edit' requires a video_to_video continuation")
        if mode == "edit" and cut_at_s + tail_duration_s > total + 0.05:
            # In edit mode the tail is REAL footage — it can't extend past the
            # clip (ffmpeg would silently truncate and desync the edit).
            raise ValidationError(
                f"tail [{cut_at_s}s, {cut_at_s + tail_duration_s:.2f}s] extends past "
                f"the clip end ({total:.2f}s) — shorten tail_duration_s or move the cut"
            )

        self._work.mkdir(parents=True, exist_ok=True)
        head = trim_head(source, cut_at_s, self._work / "head.mp4")
        if mode == "edit":
            assert self._v2v is not None  # checked above
            tail_src = extract_tail(source, cut_at_s, tail_duration_s, self._work / "tail_src.mp4")
            tail = self._v2v(
                video=tail_src, prompt=prompt, duration_s=tail_duration_s,
                out=self._work / "tail.mp4",
            )
        else:
            seed = extract_seed_frame(head, self._work / "seed.png")
            tail = self._i2v(
                seed_frame=seed, prompt=prompt, duration_s=tail_duration_s,
                out=self._work / "tail.mp4",
            )
        final = concat(head, tail, self._work / "alt_ending.mp4")
        log.info("alt_ending.done", cut_at_s=cut_at_s, mode=mode, out=str(final))
        return final


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-800:]}")


__all__ = [
    "AlternateEndingMode",
    "AlternateEndingService",
    "I2VContinuation",
    "V2VContinuation",
    "concat",
    "extract_seed_frame",
    "extract_tail",
    "probe_duration",
    "trim_head",
]
