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
    TeaserStructure,
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
        layout: str = "fill",
        ken_burns: bool = False,
    ) -> EditingTimeline:
        """Plan a single-highlight timeline that respects the platform rule.

        The kept span is clamped so that:
        - it never exceeds the platform's `max_duration_s`,
        - it is at least `min_duration_s` *when the source allows it*,
        - it never runs past the end of the source video.

        `ken_burns` carries the creator's slow-zoom choice onto the segment so a
        single-cut short honors the zoom toggle exactly like the montage path.
        """
        if source_duration_s <= 0.0:
            raise ValueError("source_duration_s must be positive to plan a short")

        start = self._clamp_start(start_s, source_duration_s, rule)
        available = source_duration_s - start
        target = self._clamp_duration(requested_duration_s, rule, available)

        segment = TimelineSegment(
            source_start_s=start, duration_s=target, label="highlight",
            ken_burns=ken_burns,
        )
        return EditingTimeline(
            segments=(segment,), width=rule.width, height=rule.height,
            layout=layout,
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
        layout: str = "fill",
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

        # Two ceilings: `budget` is the creator's *requested* length (what the
        # short should aim for) and `rule.max_duration_s` is the platform's hard
        # limit. The fit decision honors the requested budget so a 30s request
        # yields ~30s instead of silently growing to the 60s platform max — the
        # reported "duration option ignored" bug. The hard limit still caps the
        # single oversized-pick trim below.
        segments: list[TimelineSegment] = []
        used = 0.0
        seen: set[int] = set()
        for idx in selected_indices:
            if idx < 0 or idx >= len(scene_durations) or idx in seen:
                continue
            seen.add(idx)

            remaining_hard = rule.max_duration_s - used
            remaining_budget = budget - used
            if remaining_hard <= 0.01:
                break

            full_span = max(0.0, scene_durations[idx])
            # Never cut a scene mid-sentence: each scene is one narrated
            # utterance, so keep it whole when it fits the requested budget (a
            # small tolerance lets the last scene slightly overrun rather than
            # chop a word). A scene that won't fit is skipped — unless nothing is
            # chosen yet, where trimming the single oversized pick is unavoidable
            # (clamped to the platform hard limit).
            if full_span <= remaining_budget + 1.5:
                span = full_span
            elif not segments:
                span = min(full_span, remaining_hard)
            else:
                continue

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
            layout=layout,
        )

    #: Hard cap on the hook segment's own length — the teaser recipe wants the
    #: hook to land in the first ~3s, even when the source scene runs longer
    #: (a long hook scene is trimmed from the front, keeping its opening beat).
    HOOK_MAX_S = 3.0

    def plan_teaser(
        self,
        *,
        scene_durations: list[float],
        structure: TeaserStructure,
        rule: PlatformRule,
        scene_captions: list[str | None] | None = None,
        ken_burns: bool = False,
        transition: str | None = None,
        transition_duration_s: float = 0.0,
        requested_duration_s: float = 0.0,
        layout: str = "fill",
    ) -> EditingTimeline:
        """Build the teaser's `EditingTimeline`: hook → desarrollo → cliffhanger.

        Unlike `plan_montage` (which just concatenates a flat "best of" list in
        the order given), this honors the narrative shape: the hook segment is
        clamped to `HOOK_MAX_S` regardless of the source scene's own length (a
        hook must land in ~3s, even if the underlying scene runs longer — we
        keep its opening beat and drop the tail), the desarrollo scenes fill the
        middle budget, and the cliffhanger always gets its full scene (never
        trimmed) so it cuts on a real beat rather than mid-sentence.

        Returns an empty timeline when the structure is empty or nothing maps to
        a valid segment — the caller then falls back to `plan_montage` or the
        heuristic single-highlight `plan()`.
        """
        if structure.is_empty:
            return EditingTimeline(width=rule.width, height=rule.height, layout=layout)

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

        def _caption(idx: int) -> str | None:
            if scene_captions is not None and 0 <= idx < len(scene_captions):
                return scene_captions[idx]
            return None

        def _valid(idx: int) -> bool:
            return 0 <= idx < len(scene_durations)

        segments: list[TimelineSegment] = []
        used = 0.0

        # 1) Hook — always included first, clamped to HOOK_MAX_S so a long
        # source scene still opens the teaser fast.
        hook_idx = structure.hook_scene_index
        if hook_idx is not None and _valid(hook_idx):
            hook_span = min(max(0.0, scene_durations[hook_idx]), self.HOOK_MAX_S)
            if hook_span > 0.01:
                segments.append(
                    TimelineSegment(
                        source_start_s=offsets[hook_idx],
                        duration_s=hook_span,
                        label="hook",
                        caption=structure.hook_text or _caption(hook_idx),
                        ken_burns=ken_burns,
                    )
                )
                used += hook_span

        # 2) Desarrollo — fill the middle, but always leave room for the
        # cliffhanger's full span so the teaser never gets cut short of its
        # payoff-teasing beat.
        cliff_idx = structure.cliffhanger_scene_index
        cliff_span = 0.0
        if cliff_idx is not None and _valid(cliff_idx):
            cliff_span = max(0.0, scene_durations[cliff_idx])

        seen = {hook_idx} if hook_idx is not None else set()
        if cliff_idx is not None:
            seen.add(cliff_idx)
        for idx in structure.desarrollo_scene_indices:
            if not _valid(idx) or idx in seen:
                continue
            seen.add(idx)
            full_span = max(0.0, scene_durations[idx])
            if full_span <= 0.01:
                continue
            remaining_for_dev = budget - used - cliff_span
            if remaining_for_dev <= 0.01:
                break
            span = full_span if full_span <= remaining_for_dev + 1.5 else remaining_for_dev
            if span <= 0.01:
                continue
            segments.append(
                TimelineSegment(
                    source_start_s=offsets[idx],
                    duration_s=span,
                    label=f"desarrollo_{idx + 1}",
                    caption=_caption(idx),
                    ken_burns=ken_burns,
                )
            )
            used += span

        # 3) Cliffhanger — always its FULL span (never trimmed mid-sentence),
        # even if that pushes slightly past budget; only the platform hard
        # limit below can still clip it.
        if cliff_idx is not None and _valid(cliff_idx) and cliff_span > 0.01:
            remaining_hard = rule.max_duration_s - used
            span = min(cliff_span, remaining_hard) if remaining_hard > 0.01 else 0.0
            if span > 0.01:
                segments.append(
                    TimelineSegment(
                        source_start_s=offsets[cliff_idx],
                        duration_s=span,
                        label="cliffhanger",
                        caption=structure.cliffhanger_text or _caption(cliff_idx),
                        ken_burns=ken_burns,
                    )
                )

        return EditingTimeline(
            segments=tuple(segments),
            width=rule.width,
            height=rule.height,
            transition=transition,
            transition_duration_s=transition_duration_s,
            layout=layout,
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
