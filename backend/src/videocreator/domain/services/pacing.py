"""Pacing heuristics — scene-duration analysis per §3.1.

Market data: avg scene duration < 2s reads as fast meme-like treatment;
> 4s reads as dialogue-heavy and should be tightened for short-form.
Pure domain logic, no IO.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PacingClass = Literal["fast_meme", "balanced", "dialogue_heavy"]

_FAST_THRESHOLD_S = 2.0
_HEAVY_THRESHOLD_S = 4.0


@dataclass(frozen=True)
class PacingReport:
    avg_scene_duration_s: float
    classification: PacingClass
    recommendation: str
    #: per-scene suggested duration after tightening (same order as input)
    suggested_durations_s: tuple[float, ...]


def analyze_pacing(scene_durations_s: list[float]) -> PacingReport:
    """Classify pacing and suggest per-scene durations for short-form.

    fast_meme: keep as is, treat with hard cuts + SFX.
    dialogue_heavy: tighten scenes toward the 4s ceiling.
    """
    if not scene_durations_s:
        return PacingReport(
            avg_scene_duration_s=0.0,
            classification="balanced",
            recommendation="empty script — nothing to pace",
            suggested_durations_s=(),
        )
    avg = sum(scene_durations_s) / len(scene_durations_s)
    if avg < _FAST_THRESHOLD_S:
        return PacingReport(
            avg_scene_duration_s=avg,
            classification="fast_meme",
            recommendation=(
                "fast meme-like pacing — use hard cuts, beat-locked punchline, SFX"
            ),
            suggested_durations_s=tuple(scene_durations_s),
        )
    if avg > _HEAVY_THRESHOLD_S:
        return PacingReport(
            avg_scene_duration_s=avg,
            classification="dialogue_heavy",
            recommendation=(
                "dialogue-heavy for short-form — tighten scenes toward 4s, "
                "split long scenes or trim audio_text"
            ),
            suggested_durations_s=tuple(
                min(d, _HEAVY_THRESHOLD_S) for d in scene_durations_s
            ),
        )
    return PacingReport(
        avg_scene_duration_s=avg,
        classification="balanced",
        recommendation="balanced pacing — beat-snap transitions, no tightening needed",
        suggested_durations_s=tuple(scene_durations_s),
    )


__all__ = ["PacingClass", "PacingReport", "analyze_pacing"]
