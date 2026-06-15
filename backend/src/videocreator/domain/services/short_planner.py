"""ShortPlanner — turns a source episode into an `EditingTimeline` for a short.

Pure decision logic (no I/O): given how long the source video is, how long the
creator wants the short, the target platform's rule, and an optional start
offset, it computes the spans to keep and the frame size to reframe into.

The MVP picks a single highlight segment clamped to the platform's
min/max duration and the available source. The `EditingTimeline` data model
already supports multiple segments, so a future montage strategy can produce
several cuts without changing the composer or handler.
"""
from __future__ import annotations

from videocreator.domain.value_objects import (
    EditingTimeline,
    PlatformRule,
    TimelineSegment,
)


class ShortPlanner:
    """Builds an `EditingTimeline` from source/target durations and a rule."""

    def plan(
        self,
        *,
        source_duration_s: float,
        requested_duration_s: float,
        rule: PlatformRule,
        start_s: float = 0.0,
    ) -> EditingTimeline:
        """Plan a single-highlight timeline that respects the platform rule.

        The kept span is clamped so that:
        - it never exceeds the platform's `max_duration_s`,
        - it is at least `min_duration_s` *when the source allows it*,
        - it never runs past the end of the source video.
        """
        if source_duration_s <= 0.0:
            raise ValueError("source_duration_s must be positive to plan a short")

        start = self._clamp_start(start_s, source_duration_s, rule)
        available = source_duration_s - start
        target = self._clamp_duration(requested_duration_s, rule, available)

        segment = TimelineSegment(
            source_start_s=start, duration_s=target, label="highlight"
        )
        return EditingTimeline(
            segments=(segment,), width=rule.width, height=rule.height
        )

    def plan_montage(
        self,
        *,
        scene_durations: list[float],
        selected_indices: list[int],
        rule: PlatformRule,
        scene_captions: list[str | None] | None = None,
        ken_burns: bool = False,
        transition: str | None = None,
        transition_duration_s: float = 0.0,
        requested_duration_s: float = 0.0,
    ) -> EditingTimeline:
        """Build a multi-cut montage `EditingTimeline` from chosen scene indices.

        Given every source scene's length (in playback order) and the ordered,
        0-based indices the "brain" picked, map each chosen scene to its
        `[offset, offset+duration)` span in the source and concatenate them into
        a montage. The result is clamped to the platform's `max_duration_s`
        (trimming the last segment, dropping the overflow) so it always fits.

        Layer-2 polish is opt-in: pass `scene_captions` to burn each scene's line
        as a subtitle, `ken_burns=True` for a slow zoom, and a `transition`
        (+ duration) to crossfade between cuts. Omitting them yields the original
        plain hard-cut montage. Returns an empty timeline when nothing valid was
        selected — the caller then falls back to the single-highlight `plan()`.
        """
        offsets: list[float] = []
        acc = 0.0
        for dur in scene_durations:
            offsets.append(acc)
            acc += max(0.0, dur)

        if requested_duration_s > 0.0:
            target = requested_duration_s
        else:
            target = min(ShortPlanner.DEFAULT_TARGET_S, rule.max_duration_s)
        budget = min(target, rule.max_duration_s)
        
        segments: list[TimelineSegment] = []
        used = 0.0
        seen: set[int] = set()
        for idx in selected_indices:
            if idx < 0 or idx >= len(scene_durations) or idx in seen:
                continue
            seen.add(idx)
            
            remaining_hard = rule.max_duration_s - used
            if remaining_hard <= 0.01:
                break
            
            full_span = max(0.0, scene_durations[idx])
            span = min(full_span, remaining_hard)
            
            if span <= 0.01:
                continue
            caption = None
            if scene_captions is not None and idx < len(scene_captions):
                caption = scene_captions[idx]
            segments.append(
                TimelineSegment(
                    source_start_s=offsets[idx],
                    duration_s=span,
                    label=f"scene_{idx + 1}",
                    caption=caption,
                    ken_burns=ken_burns,
                )
            )
            used += span
            
            if used >= budget:
                break

        return EditingTimeline(
            segments=tuple(segments),
            width=rule.width,
            height=rule.height,
            transition=transition,
            transition_duration_s=transition_duration_s,
        )

    # ---- internals --------------------------------------------------------
    @staticmethod
    def _clamp_start(start_s: float, source_duration_s: float, rule: PlatformRule) -> float:
        """Keep `start` in range, leaving room for at least a minimal clip."""
        min_tail = min(rule.min_duration_s, source_duration_s)
        latest_start = max(0.0, source_duration_s - min_tail)
        return min(max(0.0, start_s), latest_start)

    #: Default short length when the caller does not request one. A short is
    #: a highlight, not the whole episode — defaulting to the platform max
    #: produced multi-minute "shorts" of unedited source.
    DEFAULT_TARGET_S = 30.0

    @staticmethod
    def _clamp_duration(requested_s: float, rule: PlatformRule, available_s: float) -> float:
        """Clamp the requested duration to [min, max] ∩ available source."""
        if requested_s > 0.0:
            target = requested_s
        else:
            target = min(ShortPlanner.DEFAULT_TARGET_S, rule.max_duration_s)
        target = min(target, rule.max_duration_s, available_s)
        # Honor the floor only if the source is long enough to reach it.
        return max(target, min(rule.min_duration_s, available_s))


__all__ = ["ShortPlanner"]
