"""Unit tests for the FFmpeg short composer — pure arg/filtergraph building.

The pure builder tests run everywhere; the end-to-end render test actually
shells out to FFmpeg on a synthetic source and is skipped when no binary is on
PATH, so CI without FFmpeg still passes.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from videocreator.domain.value_objects import EditingTimeline, TimelineSegment
from videocreator.infrastructure.video.short_composer import (
    FfmpegShortComposer,
    _escape_path,
    _wrap_caption,
)
from videocreator.shared.errors import ProviderError


def _timeline(*segs: tuple[float, float]) -> EditingTimeline:
    return EditingTimeline(
        segments=tuple(
            TimelineSegment(source_start_s=s, duration_s=d) for s, d in segs
        ),
        width=1080,
        height=1920,
    )


def test_filtergraph_single_segment_reframes_and_concats() -> None:
    # Arrange
    timeline = _timeline((10.0, 30.0))

    # Act
    graph, out_v, out_a = FfmpegShortComposer._build_filtergraph(timeline)

    # Assert — trim to [10, 40), center-crop to 9:16, scale to target, concat n=1
    assert "trim=start=10.0:end=40.0" in graph
    assert "crop='min(iw,ih*1080/1920)':ih" in graph
    assert "scale=1080:1920,setsar=1" in graph
    assert "concat=n=1:v=1:a=1[outv][outa]" in graph
    assert (out_v, out_a) == ("[outv]", "[outa]")


def test_filtergraph_multi_segment_concat_count() -> None:
    # Arrange — two segments
    timeline = _timeline((0.0, 5.0), (20.0, 5.0))

    # Act
    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline)

    # Assert
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" in graph


def test_build_args_maps_outputs_and_codecs() -> None:
    # Act
    args = FfmpegShortComposer._build_args(
        "ffmpeg", Path("/src/in.mp4"), _timeline((0.0, 5.0)), Path("/out/short.mp4")
    )

    # Assert — output mapping + H.264/AAC + faststart, source as input
    assert args[0] == "ffmpeg"
    assert "-filter_complex" in args
    assert args[args.index("-map") + 1] == "[outv]"
    assert "libx264" in args and "aac" in args
    assert args[-1] == str(Path("/out/short.mp4"))


async def test_compose_rejects_empty_timeline() -> None:
    # Arrange — empty timeline must fail before touching FFmpeg
    composer = FfmpegShortComposer()

    # Act / Assert
    with pytest.raises(ProviderError, match="no segments"):
        await composer.compose(Path("/src/in.mp4"), EditingTimeline(), Path("/out.mp4"))


# ---- layer 2: polish (captions / ken-burns / transitions) -----------------
def test_filtergraph_ken_burns_time_scale_not_zoompan() -> None:
    # zoompan is a still-image filter: on video it multiplies duration
    # (d output frames per INPUT frame) — the 26-minute-short bug. Ken-Burns
    # must be a time-driven upscale + center crop that preserves duration.
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=4.0, ken_burns=True),),
        width=1080, height=1920,
    )
    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline)
    assert "zoompan" not in graph
    assert "eval=frame" in graph              # per-frame zoom expression
    assert "t/4.000" in graph                 # zoom driven by segment time
    assert "crop=1080:1920" in graph          # re-crop to frame after upscale
    assert "scale=1080:1920" in graph         # normalized base before the push


def test_filtergraph_caption_emits_drawtext_with_textfile() -> None:
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=4.0, caption="hi"),),
        width=1080, height=1920,
    )
    graph, _, _ = FfmpegShortComposer._build_filtergraph(
        timeline, caption_files={0: "C\\:/tmp/cap_0.txt"}
    )
    assert "drawtext=textfile='C\\:/tmp/cap_0.txt'" in graph
    assert "x=(w-text_w)/2" in graph


def test_filtergraph_caption_skipped_when_no_file_provided() -> None:
    # caption set on segment but no file path passed → no drawtext emitted
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=4.0, caption="hi"),),
        width=1080, height=1920,
    )
    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline)
    assert "drawtext" not in graph


def test_filtergraph_transition_uses_xfade_and_acrossfade() -> None:
    timeline = EditingTimeline(
        segments=(
            TimelineSegment(source_start_s=0.0, duration_s=5.0),
            TimelineSegment(source_start_s=20.0, duration_s=5.0),
            TimelineSegment(source_start_s=40.0, duration_s=5.0),
        ),
        width=1080, height=1920, transition="fade", transition_duration_s=0.5,
    )
    graph, out_v, out_a = FfmpegShortComposer._build_filtergraph(timeline)
    # First xfade offset = dur0 - tdur = 4.5; second = (5+5-0.5) - 0.5 = 9.0
    assert "xfade=transition=fade:duration=0.5:offset=4.500" in graph
    assert "xfade=transition=fade:duration=0.5:offset=9.000[outv]" in graph
    assert "acrossfade=d=0.5" in graph
    assert "concat=" not in graph  # transition path bypasses concat
    assert (out_v, out_a) == ("[outv]", "[outa]")


def test_filtergraph_single_segment_ignores_transition() -> None:
    # A transition needs >= 2 segments; one segment falls back to concat.
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=5.0),),
        width=1080, height=1920, transition="fade", transition_duration_s=0.5,
    )
    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline)
    assert "concat=n=1:v=1:a=1" in graph
    assert "xfade" not in graph


def test_filtergraph_music_ducks_via_sidechaincompress() -> None:
    # Arrange — music requested (music_idx=1, right after the source input).
    timeline = _timeline((0.0, 5.0))

    # Act
    graph, _, out_a = FfmpegShortComposer._build_filtergraph(timeline, music_idx=1)

    # Assert — voice keys the sidechain compressor that ducks the music bed,
    # then the ducked music is mixed back under the (unducked) voice.
    assert "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300" in graph
    assert "[musv][vkey]sidechaincompress" in graph
    assert "asplit=2[vkey][vmix]" in graph
    assert "[vmix][musduck]amix=inputs=2:duration=first:dropout_transition=2[mixa]" in graph
    assert out_a == "[mixa]"


def test_filtergraph_no_music_no_ducking() -> None:
    timeline = _timeline((0.0, 5.0))
    graph, _, out_a = FfmpegShortComposer._build_filtergraph(timeline)
    assert "sidechaincompress" not in graph
    assert "amix" not in graph
    assert out_a == "[outa]"


def test_split_without_broll_warns_with_gameplay_folder_hint() -> None:
    import asyncio
    from unittest.mock import patch

    composer = FfmpegShortComposer()
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=3.0),),
        width=1080, height=1920, layout="split",
    )

    async def _fake_run(self, args, output_path):
        output_path.write_bytes(b"fake")

    with patch.object(FfmpegShortComposer, "_run", _fake_run), \
         patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        asyncio.run(composer.compose(Path("/src/in.mp4"), timeline, Path("/tmp/out_test.mp4")))

    assert any("backend/var/broll/gameplay/" in w for w in composer.warnings)


def test_wrap_caption_wraps_and_ellipsizes() -> None:
    wrapped = _wrap_caption(
        "esta es una frase bastante larga que debe partirse en varias lineas y "
        "ademas sobrar texto al final del todo para forzar el recorte"
    )
    lines = wrapped.split("\n")
    assert len(lines) <= 3
    assert wrapped.endswith("…")


def test_escape_path_handles_windows_drive_colon() -> None:
    assert _escape_path("C:\\Users\\x\\cap.txt") == "C\\:/Users/x/cap.txt"


# ---- end-to-end real render (skipped without FFmpeg) ----------------------
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _make_source(path: Path, *, seconds: int = 12) -> None:
    """Render a synthetic 16:9 source clip with video + audio via lavfi."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=640x360:duration={seconds}:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-shortest", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True,
    )


@pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="FFmpeg/ffprobe not installed")
async def test_compose_real_render_with_full_polish(tmp_path: Path) -> None:
    # Arrange — a real source + a montage with captions, ken-burns and a fade.
    source = tmp_path / "source.mp4"
    _make_source(source, seconds=12)
    timeline = EditingTimeline(
        segments=(
            TimelineSegment(source_start_s=0.0, duration_s=3.0,
                            caption="¿Qué pasará? El \"héroe\": Tico", ken_burns=True),
            TimelineSegment(source_start_s=6.0, duration_s=3.0,
                            caption="Un giro inesperado", ken_burns=True),
        ),
        width=1080, height=1920, transition="fade", transition_duration_s=0.4,
    )
    out = tmp_path / "short.mp4"

    # Act — shell out to the real FFmpeg.
    result = await FfmpegShortComposer().compose(source, timeline, out)

    # Assert — a valid vertical video was produced.
    assert result.exists() and out.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert probe.stdout.strip().startswith("1080,1920")
