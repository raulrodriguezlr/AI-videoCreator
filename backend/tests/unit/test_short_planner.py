"""Unit tests for the pure `ShortPlanner` timeline logic."""
from __future__ import annotations

import pytest

from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import PlatformRule, TeaserStructure


def _rule(**overrides: object) -> PlatformRule:
    base: dict[str, object] = {
        "platform": "shorts",
        "max_duration_s": 60.0,
        "min_duration_s": 5.0,
        "width": 1080,
        "height": 1920,
    }
    base.update(overrides)
    return PlatformRule(**base)  # type: ignore[arg-type]


def test_plan_clamps_requested_to_platform_max() -> None:
    # Arrange — ask for 120s on a 60s-max platform with a long source
    planner = ShortPlanner()

    # Act
    timeline = planner.plan(
        source_duration_s=300.0, requested_duration_s=120.0, rule=_rule()
    )

    # Assert
    assert timeline.total_duration_s == 60.0
    assert timeline.width == 1080
    assert timeline.height == 1920
    assert len(timeline.segments) == 1
    assert timeline.segments[0].source_start_s == 0.0


def test_plan_clamps_to_available_source_after_start() -> None:
    # Arrange — start near the end leaves only 8s of source
    planner = ShortPlanner()

    # Act
    timeline = planner.plan(
        source_duration_s=100.0, requested_duration_s=30.0, rule=_rule(), start_s=92.0
    )

    # Assert — kept span cannot run past the source end
    seg = timeline.segments[0]
    assert seg.source_start_s == 92.0
    assert seg.duration_s == pytest.approx(8.0)


def test_plan_requested_zero_falls_back_to_default_target() -> None:
    # A short is a highlight, not the whole episode: with no requested
    # duration the planner targets DEFAULT_TARGET_S, never the platform max.
    timeline = ShortPlanner().plan(
        source_duration_s=300.0, requested_duration_s=0.0, rule=_rule()
    )

    assert timeline.total_duration_s == ShortPlanner.DEFAULT_TARGET_S


def test_plan_short_source_uses_whole_clip_below_min() -> None:
    # Arrange — a 3s source is shorter than the 5s floor
    planner = ShortPlanner()

    # Act
    timeline = planner.plan(
        source_duration_s=3.0, requested_duration_s=30.0, rule=_rule()
    )

    # Assert — we keep the whole 3s rather than inventing footage
    assert timeline.total_duration_s == pytest.approx(3.0)


def test_plan_start_clamped_into_source() -> None:
    # Act — a start past the end is pulled back so a minimal clip still fits
    timeline = ShortPlanner().plan(
        source_duration_s=40.0, requested_duration_s=10.0, rule=_rule(), start_s=999.0
    )

    # Assert
    seg = timeline.segments[0]
    assert seg.source_start_s == pytest.approx(35.0)  # 40 - min(5, 40)
    assert seg.source_end_s <= 40.0


def test_plan_rejects_nonpositive_source() -> None:
    with pytest.raises(ValueError, match="source_duration_s"):
        ShortPlanner().plan(
            source_duration_s=0.0, requested_duration_s=10.0, rule=_rule()
        )


# ---- plan_teaser (pure) ----------------------------------------------------
def test_plan_teaser_orders_hook_desarrollo_cliffhanger() -> None:
    # 5 scenes of 10s each; hook=0 (clamped to HOOK_MAX_S), desarrollo=[1,2],
    # cliffhanger=4 kept at its full 10s span.
    planner = ShortPlanner()
    structure = TeaserStructure(
        hook_scene_index=0, hook_text="hook!",
        desarrollo_scene_indices=(1, 2),
        cliffhanger_scene_index=4, cliffhanger_text="wait for it",
    )
    timeline = planner.plan_teaser(
        scene_durations=[10.0] * 5, structure=structure, rule=_rule(),
        requested_duration_s=30.0,
    )
    labels = [s.label for s in timeline.segments]
    assert labels == ["hook", "desarrollo_2", "desarrollo_3", "cliffhanger"]
    # Hook clamped to HOOK_MAX_S even though the source scene is 10s.
    assert timeline.segments[0].duration_s == pytest.approx(ShortPlanner.HOOK_MAX_S)
    assert timeline.segments[0].caption == "hook!"
    assert timeline.segments[0].source_start_s == pytest.approx(0.0)
    # Cliffhanger keeps its FULL span (never trimmed mid-sentence).
    assert timeline.segments[-1].duration_s == pytest.approx(10.0)
    assert timeline.segments[-1].caption == "wait for it"
    assert timeline.segments[-1].source_start_s == pytest.approx(40.0)


def test_plan_teaser_empty_structure_yields_empty_timeline() -> None:
    timeline = ShortPlanner().plan_teaser(
        scene_durations=[10.0, 10.0], structure=TeaserStructure(), rule=_rule()
    )
    assert timeline.is_empty


def test_plan_teaser_cliffhanger_never_trimmed_for_desarrollo_budget() -> None:
    # Desarrollo scenes are dropped once they'd eat into the cliffhanger's
    # reserved full span, so the payoff-teasing beat always lands whole.
    planner = ShortPlanner()
    structure = TeaserStructure(
        hook_scene_index=0,
        desarrollo_scene_indices=(1, 2, 3),
        cliffhanger_scene_index=4,
    )
    timeline = planner.plan_teaser(
        scene_durations=[2.0, 10.0, 10.0, 10.0, 8.0],
        structure=structure, rule=_rule(max_duration_s=60.0),
        requested_duration_s=20.0,
    )
    cliff = next(s for s in timeline.segments if s.label == "cliffhanger")
    assert cliff.duration_s == pytest.approx(8.0)


def test_plan_teaser_desarrollo_excludes_hook_and_cliffhanger_scenes() -> None:
    # Even if desarrollo lists the hook/cliffhanger index, it must not repeat.
    planner = ShortPlanner()
    structure = TeaserStructure(
        hook_scene_index=0,
        desarrollo_scene_indices=(0, 1, 2),
        cliffhanger_scene_index=2,
    )
    timeline = planner.plan_teaser(
        scene_durations=[5.0, 5.0, 5.0], structure=structure, rule=_rule(),
    )
    labels = [s.label for s in timeline.segments]
    assert labels == ["hook", "desarrollo_2", "cliffhanger"]


def test_plan_teaser_invalid_hook_index_is_skipped() -> None:
    planner = ShortPlanner()
    structure = TeaserStructure(
        hook_scene_index=99,  # out of range
        desarrollo_scene_indices=(0,),
        cliffhanger_scene_index=1,
    )
    timeline = planner.plan_teaser(
        scene_durations=[5.0, 5.0], structure=structure, rule=_rule(),
    )
    labels = [s.label for s in timeline.segments]
    assert labels == ["desarrollo_1", "cliffhanger"]
