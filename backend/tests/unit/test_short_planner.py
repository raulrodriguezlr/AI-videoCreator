"""Unit tests for the pure `ShortPlanner` timeline logic."""
from __future__ import annotations

import pytest

from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import PlatformRule


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


def test_plan_requested_zero_falls_back_to_max() -> None:
    # Act
    timeline = ShortPlanner().plan(
        source_duration_s=300.0, requested_duration_s=0.0, rule=_rule()
    )

    # Assert
    assert timeline.total_duration_s == 60.0


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
