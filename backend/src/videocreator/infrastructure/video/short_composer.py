"""FFmpeg-backed implementation of `ShortComposerPort`.

Reframes a (typically 16:9) source video into a vertical 9:16 short, trims it to
the spans described by an `EditingTimeline`, and applies the Shorts engine's
layer-2 visual polish — all in a single FFmpeg pass via `filter_complex`:

  1. trim the video/audio to `[start, start+duration)` and reset timestamps,
  2. center-crop to the target aspect (`crop=min(iw, ih*W/H):ih`),
  3. reframe to the target size — either a plain `scale` or, when the segment
     asks for it, a slow `zoompan` Ken-Burns push for dynamism,
  4. optionally burn in a caption via `drawtext=textfile=…` (the text lives in a
     UTF-8 file so arbitrary Spanish/quotes/colons need no escaping),
then either hard-cut the segments together with `concat`, or crossfade them with
`xfade`/`acrossfade` when the timeline requests a transition.

Doing it in one invocation avoids intermediate files and re-encode rounds. The
argument list is built by pure static methods so it can be unit-tested without a
real FFmpeg binary or source file; only caption *file paths* are injected from
`compose()`, keeping the graph builder deterministic.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from videocreator.domain.services.beat_grid import BeatGrid
from videocreator.domain.value_objects import EditingTimeline
from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_FFMPEG_BIN = "ffmpeg"
_FPS = 30
# Caption layout, tuned for a 1080-wide vertical frame.
_CAPTION_WRAP_CHARS = 28
_CAPTION_MAX_LINES = 3


class FfmpegShortComposer:
    """`ShortComposerPort` adapter that shells out to a local FFmpeg binary."""

    name = "ffmpeg-short-composer"

    def __init__(self, ffmpeg_bin: str = _FFMPEG_BIN) -> None:
        self._bin = ffmpeg_bin

    async def compose(
        self,
        source_path: Path,
        timeline: EditingTimeline,
        output_path: Path,
        *,
        beat_grid: BeatGrid | None = None,
    ) -> Path:
        if timeline.is_empty:
            raise ProviderError("short-composer: timeline has no segments")
        if shutil.which(self._bin) is None:
            raise ProviderError(
                f"short-composer: '{self._bin}' not found on PATH — install FFmpeg"
            )

        if beat_grid and beat_grid.is_reliable:
            timeline = _snap_timeline_to_beats(timeline, beat_grid)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        caption_files = self._write_caption_files(timeline, output_path.parent)
        args = self._build_args(
            self._bin, source_path, timeline, output_path, caption_files
        )
        await self._run(args, output_path)
        return output_path

    # ---- caption files ----------------------------------------------------
    @staticmethod
    def _write_caption_files(
        timeline: EditingTimeline, workdir: Path
    ) -> dict[int, str]:
        """Write each segment's caption to a UTF-8 file; return escaped paths.

        Using `drawtext=textfile=` (not inline `text=`) means the caption content
        never has to be escaped for the filtergraph — only the *path* does. Keeps
        Spanish text, quotes and colons working verbatim.
        """
        out: dict[int, str] = {}
        for i, seg in enumerate(timeline.segments):
            if not seg.caption or not seg.caption.strip():
                continue
            path = workdir / f"cap_{i}.txt"
            path.write_text(_wrap_caption(seg.caption), encoding="utf-8")
            out[i] = _escape_path(str(path))
        return out

    # ---- pure arg building (unit-tested) ----------------------------------
    @staticmethod
    def _build_args(
        ffmpeg_bin: str,
        source_path: Path,
        timeline: EditingTimeline,
        output_path: Path,
        caption_files: dict[int, str] | None = None,
    ) -> list[str]:
        filtergraph, out_v, out_a = FfmpegShortComposer._build_filtergraph(
            timeline, caption_files
        )
        return [
            ffmpeg_bin,
            "-y",
            "-i", str(source_path),
            "-filter_complex", filtergraph,
            "-map", out_v,
            "-map", out_a,
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]

    @staticmethod
    def _build_filtergraph(
        timeline: EditingTimeline, caption_files: dict[int, str] | None = None
    ) -> tuple[str, str, str]:
        """Return `(filter_complex, video_out_label, audio_out_label)`.

        Per segment: trim → center-crop → reframe (scale or Ken-Burns zoompan) →
        optional caption. Segments are then hard-cut with `concat`, or crossfaded
        with `xfade`/`acrossfade` when the timeline sets a transition.
        """
        captions = caption_files or {}
        w, h = timeline.width, timeline.height
        crop = f"crop='min(iw,ih*{w}/{h})':ih"
        chains: list[str] = []
        concat_inputs: list[str] = []
        for i, seg in enumerate(timeline.segments):
            start, end = seg.source_start_s, seg.source_end_s
            vchain = [
                f"[0:v]trim=start={start}:end={end}",
                "setpts=PTS-STARTPTS",
                crop,
            ]
            if seg.ken_burns:
                frames = max(1, round(seg.duration_s * _FPS))
                vchain.append(
                    f"zoompan=z='min(zoom+0.0012,1.2)':d={frames}:s={w}x{h}:fps={_FPS}"
                )
            else:
                vchain.append(f"scale={w}:{h}")
            vchain.append("setsar=1")
            cap_path = captions.get(i)
            if cap_path:
                vchain.append(_drawtext(cap_path, h))
            chains.append(",".join(vchain) + f"[v{i}]")
            chains.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )
            concat_inputs.append(f"[v{i}][a{i}]")

        n = len(timeline.segments)
        tdur = timeline.transition_duration_s
        if timeline.transition and tdur > 0.0 and n >= 2:
            chains.extend(_crossfade_chains(timeline, tdur))
            return ";".join(chains), "[outv]", "[outa]"

        chains.append(
            f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]"
        )
        return ";".join(chains), "[outv]", "[outa]"

    # ---- subprocess -------------------------------------------------------
    async def _run(self, args: list[str], output_path: Path) -> None:
        log.info("ffmpeg.short.start", output=str(output_path))

        def run_proc() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(args, capture_output=True, check=False)

        proc = await asyncio.to_thread(run_proc)
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace")[-500:]
            raise ProviderError(
                f"ffmpeg short compose failed (exit {proc.returncode}): {tail}"
            )
        log.info("ffmpeg.short.done", output=str(output_path))


# ---- pure helpers ---------------------------------------------------------
def _crossfade_chains(timeline: EditingTimeline, tdur: float) -> list[str]:
    """Build the xfade (video) + acrossfade (audio) chains for a montage.

    `xfade` needs an absolute `offset` (when the transition starts on the running
    timeline); with a crossfade of `tdur` the combined length of two clips of
    length a and b is `a + b - tdur`, so each offset is the running length so far
    minus `tdur`. `acrossfade` overlaps automatically and just chains.
    """
    durations = [s.duration_s for s in timeline.segments]
    n = len(durations)
    out: list[str] = []
    prev_v = "[v0]"
    combined = durations[0]
    for i in range(1, n):
        offset = max(0.0, combined - tdur)
        label = "[outv]" if i == n - 1 else f"[vx{i}]"
        out.append(
            f"{prev_v}[v{i}]xfade=transition={timeline.transition}:"
            f"duration={tdur}:offset={offset:.3f}{label}"
        )
        prev_v = label
        combined = combined + durations[i] - tdur
    prev_a = "[a0]"
    for i in range(1, n):
        label = "[outa]" if i == n - 1 else f"[ax{i}]"
        out.append(f"{prev_a}[a{i}]acrossfade=d={tdur}{label}")
        prev_a = label
    return out


def _drawtext(textfile_path: str, height: int) -> str:
    """A bottom-centered, boxed caption drawtext filter reading from a file."""
    font_size = max(28, round(height * 0.030))   # ~58 on a 1920-tall frame
    margin = round(height * 0.10)                # keep clear of platform UI
    
    # Añadimos la fuente Arial explícitamente para evitar los cuadrados ("tofu boxes") 
    # cuando FFmpeg intenta renderizar saltos de línea \n o caracteres especiales 
    # con su fuente bitmap por defecto.
    font = "fontfile='C\\:/Windows/Fonts/arial.ttf'"
    
    return (
        f"drawtext=textfile='{textfile_path}':{font}:fontcolor=white:fontsize={font_size}:"
        f"line_spacing=8:box=1:boxcolor=black@0.5:boxborderw=16:"
        f"x=(w-text_w)/2:y=h-text_h-{margin}"
    )


def _escape_path(path: str) -> str:
    """Escape a filesystem path for use inside an FFmpeg filter argument.

    Forward-slash the separators and escape the Windows drive colon so
    `textfile=C\\:/Users/...` parses correctly inside `filter_complex`.
    """
    return path.replace("\\", "/").replace(":", "\\:")


def _wrap_caption(text: str) -> str:
    """Word-wrap a caption to a few short lines, ellipsizing the overflow.

    drawtext has no auto-wrap, so we insert newlines at word boundaries (~28
    chars) and cap the number of lines to keep the overlay tidy on a phone.
    """
    words = " ".join(text.split()).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > _CAPTION_WRAP_CHARS and current:
            lines.append(current)
            current = word
        else:
            current = candidate
        if len(lines) >= _CAPTION_MAX_LINES:
            break
    if current and len(lines) < _CAPTION_MAX_LINES:
        lines.append(current)
    if len(lines) >= _CAPTION_MAX_LINES:
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    return "\n".join(lines)


def _snap_timeline_to_beats(
    timeline: EditingTimeline, grid: BeatGrid
) -> EditingTimeline:
    """Snap segment boundaries to the nearest beat, preserving total coverage.

    Captions are recalculated AFTER snapping (order from §6 regression table).
    """
    from videocreator.domain.value_objects import TimelineSegment  # noqa: PLC0415

    snapped: list[TimelineSegment] = []
    for i, seg in enumerate(timeline.segments):
        start = grid.snap(seg.source_start_s)
        end = grid.snap(seg.source_end_s)
        if end <= start:
            end = start + seg.duration_s
        snapped.append(seg.model_copy(update={
            "source_start_s": start,
            "duration_s": round(end - start, 3),
        }))
    return timeline.model_copy(update={"segments": tuple(snapped)})


__all__ = ["FfmpegShortComposer"]
