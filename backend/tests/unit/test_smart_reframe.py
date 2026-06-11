"""Unit tests for Auto-Reframe (smart cropping) — subject tracking.

Pure-function tests (CropWindow smoothing, expression building, composer
filtergraph integration) run everywhere. Tests that need real video decoding
are marked with `pytest.importorskip("cv2")` / skip when MediaPipe is absent,
so CI without those optional deps still passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from videocreator.domain.value_objects import EditingTimeline, TimelineSegment
from videocreator.infrastructure.video.short_composer import FfmpegShortComposer
from videocreator.infrastructure.video.smart_reframe import (
    CropWindow,
    analyze_segment,
    analyze_timeline,
    crop_x_expression,
)


# ---- CropWindow smoothing ---------------------------------------------------
def test_smooth_applies_moving_average_window_3() -> None:
    from videocreator.infrastructure.video.smart_reframe import _smooth  # noqa: PLC0415

    samples = [
        CropWindow(0.0, 0.0),
        CropWindow(1.0, 0.3),
        CropWindow(2.0, 0.9),
        CropWindow(3.0, 0.3),
    ]

    smoothed = _smooth(samples)

    # index 0: avg(0.0, 0.3) — window clipped at the left edge
    assert smoothed[0].center_x_frac == pytest.approx(0.15)
    # index 1: avg(0.0, 0.3, 0.9)
    assert smoothed[1].center_x_frac == pytest.approx(0.4)
    # index 2: avg(0.3, 0.9, 0.3)
    assert smoothed[2].center_x_frac == pytest.approx(0.5)
    # index 3: avg(0.9, 0.3) — window clipped at the right edge
    assert smoothed[3].center_x_frac == pytest.approx(0.6)
    # timestamps are preserved verbatim
    assert [w.time_s for w in smoothed] == [0.0, 1.0, 2.0, 3.0]


def test_smooth_passthrough_for_fewer_than_two_samples() -> None:
    from videocreator.infrastructure.video.smart_reframe import _smooth  # noqa: PLC0415

    assert _smooth([]) == []
    one = [CropWindow(0.0, 0.5)]
    assert _smooth(one) == one


# ---- crop_x_expression: exact expressions ------------------------------------
def test_crop_x_expression_two_windows_exact() -> None:
    windows = [CropWindow(0.0, 0.3), CropWindow(2.0, 0.7)]

    expr = crop_x_expression(windows)

    assert expr == (
        "max(0\\,min(iw-(min(iw\\,ih*9/16))\\,"
        "(if(lt(t\\,2)\\,lerp(0.3\\,0.7\\,max(0\\,min(1\\,(t-0)/2)))\\,0.7))"
        "*iw-(min(iw\\,ih*9/16))/2))"
    )


def test_crop_x_expression_three_windows_exact() -> None:
    windows = [CropWindow(0.0, 0.2), CropWindow(1.0, 0.5), CropWindow(2.0, 0.8)]

    expr = crop_x_expression(windows)

    assert expr == (
        "max(0\\,min(iw-(min(iw\\,ih*9/16))\\,"
        "(if(lt(t\\,1)\\,lerp(0.2\\,0.5\\,max(0\\,min(1\\,(t-0)/1)))\\,"
        "if(lt(t\\,2)\\,lerp(0.5\\,0.8\\,max(0\\,min(1\\,(t-1)/1)))\\,0.8)))"
        "*iw-(min(iw\\,ih*9/16))/2))"
    )


def test_crop_x_expression_single_window() -> None:
    expr = crop_x_expression([CropWindow(0.0, 0.65)])

    # No interpolation needed — a constant center fraction.
    assert expr == (
        "max(0\\,min(iw-(min(iw\\,ih*9/16))\\,(0.65)*iw-(min(iw\\,ih*9/16))/2))"
    )
    assert "if(" not in expr
    assert "lerp(" not in expr


def test_crop_x_expression_empty_returns_none() -> None:
    assert crop_x_expression([]) is None


def test_crop_x_expression_custom_crop_w_expr_substituted() -> None:
    windows = [CropWindow(0.0, 0.3), CropWindow(2.0, 0.7)]

    expr = crop_x_expression(windows, crop_w_expr="iw/2")

    assert expr is not None
    assert "(iw/2)" in expr
    assert "min(iw\\,ih*9/16)" not in expr


# ---- crop_x_expression: clamping + escaping invariants ------------------------
def test_crop_x_expression_clamps_to_frame_bounds() -> None:
    windows = [CropWindow(0.0, 0.0), CropWindow(1.0, 1.0)]

    expr = crop_x_expression(windows)

    assert expr is not None
    # Outer clamp: 0 <= x <= iw - out_w
    assert expr.startswith("max(0\\,min(iw-")
    # The interpolation fraction itself is also clamped to [0, 1].
    assert "max(0\\,min(1\\," in expr


def test_crop_x_expression_escapes_commas_for_filtergraph() -> None:
    windows = [CropWindow(0.0, 0.3), CropWindow(2.0, 0.7)]

    expr = crop_x_expression(windows)

    assert expr is not None
    # Every comma must be filtergraph-escaped (preceded by a backslash) — an
    # unescaped comma would split this into multiple "filters" in filter_complex.
    assert "," in expr  # sanity: the expression does contain commas
    for i, ch in enumerate(expr):
        if ch == ",":
            assert expr[i - 1] == "\\", f"unescaped comma at index {i}: {expr!r}"
    assert "\\,lerp(" in expr


# ---- crop_x_expression: downsampling for very long segments -------------------
def test_crop_x_expression_downsamples_above_twelve_windows() -> None:
    windows = [CropWindow(float(i), (i % 10) / 10.0) for i in range(13)]

    expr = crop_x_expression(windows)

    assert expr is not None
    # 8 keyframes -> 7 piecewise segments -> 7 if/lerp pairs.
    assert expr.count("if(") == 7
    assert expr.count("lerp(") == 7


def test_crop_x_expression_keeps_short_lists_unchanged() -> None:
    windows = [CropWindow(float(i), 0.5) for i in range(12)]

    expr = crop_x_expression(windows)

    assert expr is not None
    assert expr.count("if(") == 11  # 12 keyframes -> 11 piecewise segments


def test_crop_x_expression_dedupes_duplicate_timestamps() -> None:
    windows = [
        CropWindow(0.0, 0.2),
        CropWindow(0.0, 0.4),  # duplicate time — first one wins
        CropWindow(1.0, 0.6),
    ]

    expr = crop_x_expression(windows)

    assert expr is not None
    assert "0.2" in expr
    assert "0.4" not in expr


# ---- analyze_segment / analyze_timeline: graceful fallback --------------------
def test_analyze_segment_empty_when_cv2_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate "cv2 is not installed" without needing to uninstall it.
    monkeypatch.setitem(sys.modules, "cv2", None)

    result = analyze_segment(Path("does-not-matter.mp4"), 0.0, 5.0)

    assert result == []


def test_analyze_segment_empty_for_degenerate_span() -> None:
    cv2 = pytest.importorskip("cv2")
    assert cv2 is not None  # keep the import alive for the skip check

    assert analyze_segment(Path("anything.mp4"), 5.0, 5.0) == []
    assert analyze_segment(Path("anything.mp4"), 5.0, 4.0) == []


def test_analyze_segment_empty_when_video_cannot_be_opened() -> None:
    pytest.importorskip("cv2")

    result = analyze_segment(Path("this-file-does-not-exist.mp4"), 0.0, 5.0)

    assert result == []


def test_analyze_timeline_skips_segments_with_empty_analysis() -> None:
    pytest.importorskip("cv2")

    timeline = EditingTimeline(
        segments=(
            TimelineSegment(source_start_s=0.0, duration_s=5.0),
            TimelineSegment(source_start_s=10.0, duration_s=5.0),
        ),
        width=1080, height=1920,
    )

    # A nonexistent source video -> every segment's analysis is empty -> the
    # whole timeline mapping is empty (composer keeps its centered crop).
    result = analyze_timeline(Path("this-file-does-not-exist.mp4"), timeline)

    assert result == {}


# ---- composer integration: per-segment crop_x --------------------------------
def _two_segment_timeline() -> EditingTimeline:
    return EditingTimeline(
        segments=(
            TimelineSegment(source_start_s=0.0, duration_s=5.0),
            TimelineSegment(source_start_s=10.0, duration_s=5.0),
        ),
        width=1080, height=1920,
    )


def test_filtergraph_uses_provided_x_expression_for_targeted_segment() -> None:
    timeline = _two_segment_timeline()
    expr = crop_x_expression([CropWindow(0.0, 0.3), CropWindow(2.0, 0.7)])
    assert expr is not None

    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline, crop_x={0: expr})

    # Segment 0 gets the panning crop with the exact x expression.
    assert f"crop=w='min(iw,ih*1080/1920)':h=ih:x={expr}:y=0" in graph
    # Segment 1 (no entry in crop_x) keeps the original centered crop.
    assert "crop='min(iw,ih*1080/1920)':ih" in graph


def test_filtergraph_stays_centered_when_crop_x_is_none_or_empty() -> None:
    timeline = _two_segment_timeline()

    graph_none, _, _ = FfmpegShortComposer._build_filtergraph(timeline, crop_x=None)
    graph_empty, _, _ = FfmpegShortComposer._build_filtergraph(timeline, crop_x={})

    for graph in (graph_none, graph_empty):
        assert graph.count("crop='min(iw,ih*1080/1920)':ih") == 2
        assert "x=max(0" not in graph


def test_filtergraph_crop_x_combines_with_ken_burns() -> None:
    timeline = EditingTimeline(
        segments=(TimelineSegment(source_start_s=0.0, duration_s=4.0, ken_burns=True),),
        width=1080, height=1920,
    )
    expr = crop_x_expression([CropWindow(0.0, 0.4)])
    assert expr is not None

    graph, _, _ = FfmpegShortComposer._build_filtergraph(timeline, crop_x={0: expr})

    # Panning crop is applied before the Ken-Burns push-in, which is unaffected.
    assert f"crop=w='min(iw,ih*1080/1920)':h=ih:x={expr}:y=0" in graph
    assert "eval=frame" in graph
    assert "crop=1080:1920" in graph  # Ken-Burns re-crop after the time-driven scale
