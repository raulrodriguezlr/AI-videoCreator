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

# Background-music ducking (sidechaincompress keyed off the voice track). The
# music plays at `_MUSIC_BASE_VOLUME` and gets compressed down whenever the
# voice crosses `_DUCK_THRESHOLD`, so it audibly steps out of the way while
# someone's talking and comes back up in the gaps.
_MUSIC_BASE_VOLUME = 0.35
_DUCK_THRESHOLD = 0.03
_DUCK_RATIO = 8
_DUCK_ATTACK_MS = 20
_DUCK_RELEASE_MS = 300


class FfmpegShortComposer:
    """`ShortComposerPort` adapter that shells out to a local FFmpeg binary."""

    name = "ffmpeg-short-composer"

    def __init__(self, ffmpeg_bin: str = _FFMPEG_BIN) -> None:
        self._bin = ffmpeg_bin
        # Non-silent-degradation ledger: populated fresh on every `compose()`
        # call whenever a requested feature falls back to something lesser
        # (smart-reframe unavailable, no music bed, split→fill for missing
        # b-roll, ASR captions unavailable...). The handler reads this right
        # after awaiting `compose()` and surfaces it to the caller/response —
        # see `short_render.py` / `shorts.py`.
        self.warnings: list[str] = []

    async def compose(
        self,
        source_path: Path,
        timeline: EditingTimeline,
        output_path: Path,
        *,
        beat_grid: BeatGrid | None = None,
        crop_x: dict[int, str] | None = None,
        broll_path: Path | None = None,
        music_path: Path | None = None,
        asr_audio_path: Path | None = None,
        script_lines: list[str] | None = None,
    ) -> Path:
        self.warnings = []
        if timeline.is_empty:
            raise ProviderError("short-composer: timeline has no segments")
        if shutil.which(self._bin) is None:
            raise ProviderError(
                f"short-composer: '{self._bin}' not found on PATH — install FFmpeg"
            )

        if getattr(timeline, "layout", "fill") == "split" and broll_path is None:
            self.warnings.append(
                "split layout requested but no b-roll available — degraded to "
                "full-frame fill. Deja mp4s en backend/var/broll/gameplay/ "
                "(o usa 'Poblar con clips libres' en Ajustes) para activar el split."
            )

        if beat_grid and beat_grid.is_reliable:
            timeline = _snap_timeline_to_beats(timeline, beat_grid)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        caption_files = self._write_caption_files(timeline, output_path.parent)
        # Prefer the Hormozi-style word-by-word .ass overlay; when it's built it
        # replaces the per-segment boxed `drawtext` caption entirely.
        subtitle_ass = self._build_ass_subtitle(
            timeline, output_path.parent,
            asr_audio_path=asr_audio_path, script_lines=script_lines,
            warnings=self.warnings,
        )
        if subtitle_ass:
            caption_files = {}
        args = self._build_args(
            self._bin, source_path, timeline, output_path, caption_files, crop_x,
            subtitle_ass, broll_path, music_path,
        )
        await self._run(args, output_path)
        return output_path

    # ---- word-by-word .ass subtitle (Hormozi look) ------------------------
    @staticmethod
    def _build_ass_subtitle(
        timeline: EditingTimeline,
        workdir: Path,
        *,
        asr_audio_path: Path | None = None,
        script_lines: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> str | None:
        """Build a single word-by-word `.ass` for the whole short, or `None`.

        Two timing sources, in priority order:

        1. **Real ASR** (`teaser` pipeline): when `asr_audio_path` is given, run
           local Whisper on the actual rendered audio and correct its text
           against `script_lines` (see `ass_captions.build_captions_from_asr`).
           This is the fix for caption/voice desync — real timing instead of an
           estimate. Any failure (missing `faster-whisper`, transcription
           error) records a warning and falls through to the estimate below
           rather than breaking the render.
        2. **Estimated timing** (`legacy` pipeline / ASR fallback): spreads each
           segment's caption text evenly across that segment's slot in the
           OUTPUT timeline (cumulative segment durations, since segments are
           hard-cut/concatenated). Timings are estimates — good enough for the
           reveal, but the reason the `teaser` pipeline replaces this path.

        Returns an ffmpeg-escaped path, or `None` when no segment has a caption
        and no ASR audio was supplied.
        """
        from videocreator.infrastructure.video.ass_captions import (  # noqa: PLC0415
            WordTiming,
            build_ass,
            build_captions_from_asr,
            extract_keywords_from_script,
            style_for,
        )

        style = style_for(getattr(timeline, "template", None))

        if asr_audio_path is not None and script_lines:
            asr_words = build_captions_from_asr(asr_audio_path, script_lines)
            if asr_words:
                keywords: set[str] = set()
                for line in script_lines:
                    keywords |= extract_keywords_from_script(line)
                out = workdir / "subs.ass"
                build_ass(asr_words, keywords, out, style=style)
                return _escape_path(str(out))
            if warnings is not None:
                warnings.append(
                    "ASR captions unavailable (faster-whisper missing or "
                    "transcription failed) — fell back to estimated timing"
                )

        words: list[WordTiming] = []
        keywords = set()
        offset = 0.0
        for seg in timeline.segments:
            text = (seg.caption or "").strip()
            dur = max(seg.duration_s, 0.1)
            if text:
                keywords |= extract_keywords_from_script(text)
                toks = text.replace("**", "").split()  # markers drive highlight
                if toks:
                    per = dur / len(toks)
                    for j, tok in enumerate(toks):
                        s = offset + j * per
                        words.append(WordTiming(word=tok, start_s=s, end_s=s + per))
            offset += dur

        if not words:
            return None
        out = workdir / "subs.ass"
        build_ass(words, keywords, out, style=style)
        return _escape_path(str(out))

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
            path.write_text(_wrap_caption(seg.caption), encoding="utf-8", newline="\n")
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
        crop_x: dict[int, str] | None = None,
        subtitle_ass: str | None = None,
        broll_path: Path | None = None,
        music_path: Path | None = None,
    ) -> list[str]:
        # Inputs: [0]=source, then optional b-roll, then optional music. Both
        # extra inputs loop forever (-stream_loop -1); the graph clamps to the
        # main video/audio length. b-roll stays index 1 so the split graph's
        # hard-coded [1:v] is always correct.
        inputs = ["-i", str(source_path)]
        next_idx = 1
        if broll_path is not None:
            inputs += ["-stream_loop", "-1", "-i", str(broll_path)]
            next_idx += 1
        music_idx: int | None = None
        if music_path is not None:
            inputs += ["-stream_loop", "-1", "-i", str(music_path)]
            music_idx = next_idx
            next_idx += 1
        filtergraph, out_v, out_a = FfmpegShortComposer._build_filtergraph(
            timeline, caption_files, crop_x, subtitle_ass,
            broll=broll_path is not None, music_idx=music_idx,
        )
        return [
            ffmpeg_bin,
            "-y",
            *inputs,
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
        timeline: EditingTimeline,
        caption_files: dict[int, str] | None = None,
        crop_x: dict[int, str] | None = None,
        subtitle_ass: str | None = None,
        broll: bool = False,
        music_idx: int | None = None,
    ) -> tuple[str, str, str]:
        """Return `(filter_complex, video_out_label, audio_out_label)`.

        Per segment: trim → crop (centered, or panned to follow the subject when
        `crop_x` provides an x-position expression for that segment) → reframe
        (scale or Ken-Burns zoompan) → optional caption. Segments are then
        hard-cut with `concat`, or crossfaded with `xfade`/`acrossfade` when the
        timeline sets a transition.
        """
        captions = caption_files or {}
        crop_exprs = crop_x or {}
        w, h = timeline.width, timeline.height
        layout = getattr(timeline, "layout", "fill") or "fill"
        # Split-screen needs a second input ([1:v] = looped b-roll); without one
        # it silently degrades to a normal full-frame reframe.
        split = layout == "split" and broll
        if split:
            h_top = (int(h * 0.62) // 2) * 2   # main video panel (top)
            h_bot = h - h_top                  # b-roll panel (bottom)
            fh = h_top                         # per-segment reframe target height
            seg_layout = "fill"                # top panel always crop-fills
        else:
            h_top = h_bot = 0
            fh = h
            seg_layout = layout
        center_crop = f"crop='min(iw,ih*{w}/{fh})':ih"
        chains: list[str] = []
        concat_inputs: list[str] = []
        for i, seg in enumerate(timeline.segments):
            start, end = seg.source_start_s, seg.source_end_s
            trim = f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS"
            cap_path = captions.get(i)
            cap = _drawtext(cap_path, fh) if cap_path else None

            if seg_layout == "fit_blur":
                # Whole frame fits (no crop, less zoom); margins filled with a
                # blurred, zoomed copy of the same frame instead of black bars.
                chains.extend(
                    FfmpegShortComposer._fit_blur_statements(i, trim, w, fh, cap)
                )
            else:
                x_expr = crop_exprs.get(i)
                crop = (
                    f"crop=w='min(iw,ih*{w}/{fh})':h=ih:x={x_expr}:y=0"
                    if x_expr is not None
                    else center_crop
                )
                vchain = [trim, crop]
                if seg.ken_burns:
                    # Ken-Burns on VIDEO: a time-driven upscale + center crop.
                    # (`zoompan` is for still images — on video it emits `d`
                    # output frames PER input frame, inflating a 60s short into
                    # a half-hour of frozen frames.)
                    dur = max(seg.duration_s, 0.1)
                    grow = 0.12  # 12% push-in over the segment
                    vchain.append(f"scale={w}:{fh}")
                    vchain.append(
                        f"scale=w='trunc({w}*(1+{grow}*t/{dur:.3f})/2)*2':"
                        f"h='trunc({fh}*(1+{grow}*t/{dur:.3f})/2)*2':eval=frame"
                    )
                    vchain.append(f"crop={w}:{fh}")
                else:
                    vchain.append(f"scale={w}:{fh}")
                vchain.append("setsar=1")
                if cap:
                    vchain.append(cap)
                chains.append(",".join(vchain) + f"[v{i}]")

            chains.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )
            concat_inputs.append(f"[v{i}][a{i}]")

        n = len(timeline.segments)
        tdur = timeline.transition_duration_s
        if timeline.transition and tdur > 0.0 and n >= 2:
            chains.extend(_crossfade_chains(timeline, tdur))
            v_out, a_out = "[outv]", "[outa]"
        else:
            chains.append(
                f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]"
            )
            v_out, a_out = "[outv]", "[outa]"

        # Split-screen: stack the looped b-roll ([1:v]) under the main panel.
        if split:
            chains.append(
                f"[1:v]scale={w}:{h_bot}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h_bot},setsar=1[botv]"
            )
            chains.append(f"{v_out}[botv]vstack=inputs=2[stackv]")
            v_out = "[stackv]"

        # Word-by-word .ass burned over the assembled timeline (one pass, after
        # concat/crossfade/stack so its timestamps match the final output clock).
        if subtitle_ass:
            chains.append(f"{v_out}ass='{subtitle_ass}'[subv]")
            v_out = "[subv]"

        # Royalty-free background music ([music_idx:a], looped via -stream_loop)
        # mixed UNDER the voice, DUCKED via sidechaincompress so it drops out of
        # the way whenever the voice speaks (keyed off the voice track) instead
        # of playing at one fixed low volume the whole time; `duration=first`
        # clamps the mix to the (main) voice track length.
        if music_idx is not None:
            chains.append(f"[{music_idx}:a]volume={_MUSIC_BASE_VOLUME}[musv]")
            # `asplit` because the voice track feeds BOTH the sidechain key
            # input and the final mix; a filter output can only be consumed
            # once otherwise.
            chains.append(f"{a_out}asplit=2[vkey][vmix]")
            chains.append(
                f"[musv][vkey]sidechaincompress=threshold={_DUCK_THRESHOLD}:"
                f"ratio={_DUCK_RATIO}:attack={_DUCK_ATTACK_MS}:"
                f"release={_DUCK_RELEASE_MS}[musduck]"
            )
            chains.append(
                "[vmix][musduck]amix=inputs=2:duration=first:dropout_transition=2[mixa]"
            )
            a_out = "[mixa]"
        return ";".join(chains), v_out, a_out

    @staticmethod
    def _fit_blur_statements(
        i: int, trim_chain: str, w: int, h: int, caption: str | None
    ) -> list[str]:
        """Filtergraph statements for the `fit_blur` layout of one segment.

        Splits the trimmed source into a foreground and a background copy:
        - background is scaled to *cover* the WxH frame, hard-cropped, and
          gaussian-blurred — this replaces the black letterbox bars,
        - foreground is scaled to *fit* inside WxH (whole frame visible, less
          zoom on the subject) and centered over the blur.
        Produces the segment's `[v{i}]` label (with the caption burned on top,
        if any). Emitted as separate `;`-joined statements because `split`/
        `overlay` need named pads, unlike the linear comma chain of `fill`.
        """
        fg, bg, bgb, fgs, out = f"fg{i}", f"bg{i}", f"bgb{i}", f"fgs{i}", f"v{i}"
        stmts = [
            f"{trim_chain},split=2[{fg}][{bg}]",
            f"[{bg}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=20[{bgb}]",
            f"[{fg}]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[{fgs}]",
        ]
        overlay = f"[{bgb}][{fgs}]overlay=(W-w)/2:(H-h)/2"
        if caption:
            overlay += f",{caption}"
        stmts.append(overlay + f"[{out}]")
        return stmts

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
