"""Auto-reframe (smart cropping) — subject tracking for 16:9 → 9:16 shorts.

`short_composer.py` reframes a horizontal source into a vertical short with a
plain center-crop (`crop='min(iw,ih*W/H)':ih`). When the subject sits near the
left or right edge of the frame, that crop slices them in half — exactly the
"talking head cut off" problem OpusClip's Auto-Reframe solves.

This module samples each timeline segment's video, finds where the subject
(face, else person) sits horizontally per sample, smooths that series, and
turns it into an FFmpeg `crop` `x` expression that pans the crop window to
follow the subject over the segment's duration.

Everything here is **best-effort and additive**: OpenCV and MediaPipe are both
optional/lazy imports. If either is missing, or detection finds nothing, the
analysis step returns an empty result and the composer falls back to its
existing centered crop — a smart-reframe failure must never break a render.

No paid APIs are used.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from videocreator.shared.logging import get_logger

if TYPE_CHECKING:
    from videocreator.domain.value_objects import EditingTimeline

log = get_logger(__name__)

# Moving-average window for smoothing the per-sample center series so the crop
# doesn't jitter frame-to-frame as detections flicker.
_SMOOTHING_WINDOW = 3
# Above this many keyframes, downsample the expression to keep it readable and
# bounded in length (FFmpeg filtergraph args have practical size limits).
_MAX_WINDOWS = 12
_DOWNSAMPLE_TARGET = 8
# Default target aspect for the `crop` filter's `w` expression, pre-escaped
# for embedding inside a `filter_complex` argument (commas are filtergraph
# separators, so literal commas in math expressions need `\,`).
_DEFAULT_CROP_W_EXPR = r"min(iw\,ih*9/16)"


@dataclass(frozen=True)
class CropWindow:
    """One sampled (and smoothed) subject-center keyframe.

    `time_s` is segment-local (0 at the segment's `source_start_s`).
    `center_x_frac` is the subject's horizontal center as a fraction of the
    *source* frame width, in `[0, 1]`.
    """

    time_s: float
    center_x_frac: float


# ============================================================================
# Frame analysis (OpenCV + MediaPipe, both lazy/optional)
# ============================================================================
def analyze_segment(
    video_path: Path,
    start_s: float,
    end_s: float,
    *,
    samples_per_second: float = 1.0,
) -> list[CropWindow]:
    """Sample `[start_s, end_s)` and return smoothed subject-center keyframes.

    Detection order per sample:
      1. MediaPipe face detection (`model_selection=1`, tuned for full-range/
         further-away faces — typical of a 16:9 talking-head or scene shot).
      2. OpenCV's HOG person detector, if no face was found.
      3. Frame center (`0.5`), if neither finds anything.

    Returns `[]` (caller keeps the existing center-crop) when:
      - OpenCV (or MediaPipe) isn't installed,
      - the video can't be opened,
      - or the segment is degenerate (`end_s <= start_s`).
    """
    if end_s <= start_s:
        return []

    try:
        import cv2  # noqa: PLC0415 — lazy: optional/heavy dep
    except ImportError:
        log.info("smart_reframe.cv2_not_installed")
        return []

    face_detector = _build_face_detector()
    person_detector = _build_person_detector(cv2)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.info("smart_reframe.video_open_failed", path=str(video_path))
        cap.release()
        return []

    try:
        samples = _collect_samples(
            cap, cv2, start_s, end_s, samples_per_second,
            face_detector=face_detector, person_detector=person_detector,
        )
    finally:
        cap.release()

    if not samples:
        return []
    return _smooth(samples)


def _collect_samples(
    cap: object,
    cv2: object,
    start_s: float,
    end_s: float,
    samples_per_second: float,
    *,
    face_detector: object | None,
    person_detector: object | None,
) -> list[CropWindow]:
    step_s = 1.0 / samples_per_second if samples_per_second > 0 else (end_s - start_s)
    samples: list[CropWindow] = []
    t = start_s
    while t < end_s:
        frame = _read_frame_at(cap, cv2, t)
        if frame is not None:
            center = _detect_center(frame, cv2, face_detector, person_detector)
            samples.append(CropWindow(time_s=round(t - start_s, 3), center_x_frac=center))
        t += step_s
    return samples


def _read_frame_at(cap: object, cv2: object, t_s: float) -> object | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)  # type: ignore[attr-defined]
    ok, frame = cap.read()  # type: ignore[attr-defined]
    return frame if ok else None


def _build_face_detector() -> object | None:
    """Build a MediaPipe face detector, or `None` when MediaPipe is missing or
    its legacy `solutions` API is unavailable (newer wheels drop it). Either
    way the caller degrades to the OpenCV HOG person detector — never crashes."""
    try:
        import mediapipe as mp  # noqa: PLC0415 — lazy: optional/heavy dep
    except ImportError:
        log.info("smart_reframe.mediapipe_not_installed")
        return None
    try:
        return mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        )
    except AttributeError:
        log.info("smart_reframe.mediapipe_solutions_unavailable",
                 version=getattr(mp, "__version__", "?"))
        return None


def _build_person_detector(cv2: object) -> object:
    """Build an OpenCV HOG person detector — bundled with opencv, no extra deps."""
    hog = cv2.HOGDescriptor()  # type: ignore[attr-defined]
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())  # type: ignore[attr-defined]
    return hog


def _detect_center(
    frame: object,
    cv2: object,
    face_detector: object | None,
    person_detector: object,
) -> float:
    """Return the detected subject's horizontal center fraction, else `0.5`."""
    width = frame.shape[1]  # type: ignore[attr-defined]

    if face_detector is not None:
        center = _face_center(frame, cv2, face_detector, width)
        if center is not None:
            return center

    center = _person_center(frame, person_detector, width)
    if center is not None:
        return center

    return 0.5


def _face_center(frame: object, cv2: object, detector: object, width: int) -> float | None:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # type: ignore[attr-defined]
    result = detector.process(rgb)  # type: ignore[attr-defined]
    detections = getattr(result, "detections", None)
    if not detections:
        return None
    centers = []
    for det in detections:
        bbox = det.location_data.relative_bounding_box
        centers.append(bbox.xmin + bbox.width / 2.0)
    return sum(centers) / len(centers)


def _person_center(frame: object, hog: object, width: int) -> float | None:
    rects, _weights = hog.detectMultiScale(  # type: ignore[attr-defined]
        frame, winStride=(8, 8), padding=(8, 8), scale=1.05
    )
    if rects is None or len(rects) == 0:
        return None
    centers = [(x + w / 2.0) / width for (x, y, w, h) in rects]
    return sum(centers) / len(centers)


def _smooth(samples: list[CropWindow]) -> list[CropWindow]:
    """Simple moving-average (window=3) over `center_x_frac` to kill jitter."""
    n = len(samples)
    if n < 2:
        return samples
    out: list[CropWindow] = []
    half = _SMOOTHING_WINDOW // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        window = samples[lo:hi]
        avg = sum(s.center_x_frac for s in window) / len(window)
        out.append(CropWindow(time_s=samples[i].time_s, center_x_frac=avg))
    return out


# ============================================================================
# FFmpeg expression building (pure — unit-tested precisely)
# ============================================================================
def crop_x_expression(
    windows: list[CropWindow],
    crop_w_expr: str = _DEFAULT_CROP_W_EXPR,
) -> str | None:
    """Build a `crop` filter `x` expression that pans across `windows`.

    Returns `None` for an empty/degenerate `windows` list — the caller should
    keep its existing centered crop in that case.

    The expression piecewise-linearly interpolates `center_x_frac` over
    segment-local time `t` between consecutive keyframes (clamping the
    interpolation fraction to `[0, 1]` so values outside the keyframe span
    hold at the nearest endpoint), converts the resulting fraction to a pixel
    offset (`center * iw - out_w / 2`), and clamps that offset to
    `[0, iw - out_w]` so the crop window never runs off the source frame.

    `out_w` is the crop filter's own output width — `crop_w_expr` (escaped for
    `filter_complex`, e.g. `min(iw\\,ih*9/16)`) is reused verbatim so `out_w`
    matches whatever width the caller's `crop=w=...` actually produces.

    More than `_MAX_WINDOWS` keyframes are evenly downsampled to
    `_DOWNSAMPLE_TARGET` to keep the expression's length sane.
    """
    points = _dedupe_by_time(windows)
    if not points:
        return None
    if len(points) == 1:
        center_expr = _fmt(points[0].center_x_frac)
    else:
        if len(points) > _MAX_WINDOWS:
            points = _downsample(points, _DOWNSAMPLE_TARGET)
        center_expr = _piecewise_linear(points)

    out_w = f"({crop_w_expr})"
    pixel_x = f"({center_expr})*iw-{out_w}/2"
    return f"max(0\\,min(iw-{out_w}\\,{pixel_x}))"


def _piecewise_linear(points: list[CropWindow]) -> str:
    """Build nested `if(lt(t,...), lerp(...), ...)` for sorted, deduped points."""
    # Innermost (last) branch: hold the final keyframe's value for t beyond it.
    expr = _fmt(points[-1].center_x_frac)
    for i in range(len(points) - 2, -1, -1):
        a, b = points[i], points[i + 1]
        span = b.time_s - a.time_s
        frac = f"max(0\\,min(1\\,(t-{_fmt(a.time_s)})/{_fmt(span)}))"
        lerp = f"lerp({_fmt(a.center_x_frac)}\\,{_fmt(b.center_x_frac)}\\,{frac})"
        expr = f"if(lt(t\\,{_fmt(b.time_s)})\\,{lerp}\\,{expr})"
    return expr


def _dedupe_by_time(windows: list[CropWindow]) -> list[CropWindow]:
    """Sort by time and drop windows sharing a timestamp (keep the first)."""
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: w.time_s)
    out: list[CropWindow] = [ordered[0]]
    for w in ordered[1:]:
        if w.time_s > out[-1].time_s:
            out.append(w)
    return out


def _downsample(points: list[CropWindow], target: int) -> list[CropWindow]:
    """Evenly pick ~`target` points from `points`, always keeping the ends."""
    n = len(points)
    if target >= n:
        return points
    if target <= 1:
        return [points[0]]
    step = (n - 1) / (target - 1)
    indices = sorted({round(i * step) for i in range(target)})
    return [points[i] for i in indices]


def _fmt(value: float) -> str:
    """Render a float for an FFmpeg expression without noisy trailing zeros."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


# ============================================================================
# Timeline-level orchestration
# ============================================================================
def analyze_timeline(
    video_path: Path,
    timeline: EditingTimeline,
    *,
    samples_per_second: float = 1.0,
) -> dict[int, str]:
    """Analyze every segment of `timeline` and return `{segment_index: x_expr}`.

    Segments where analysis finds nothing (missing deps, no detections, open
    failure, …) are simply absent from the returned mapping — the composer
    keeps its centered crop for those.
    """
    out: dict[int, str] = {}
    for i, seg in enumerate(timeline.segments):
        windows = analyze_segment(
            video_path, seg.source_start_s, seg.source_end_s,
            samples_per_second=samples_per_second,
        )
        expr = crop_x_expression(windows)
        if expr is not None:
            out[i] = expr
    return out


__all__ = [
    "CropWindow",
    "analyze_segment",
    "analyze_timeline",
    "crop_x_expression",
]
