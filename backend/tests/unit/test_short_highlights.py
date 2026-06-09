"""Unit tests for the Shorts engine "brain" (Fase 6 layer 1).

Two pure-ish pieces:
- `ShortPlanner.plan_montage` — maps chosen scene indices to a multi-cut
  `EditingTimeline`, clamped to the platform budget (pure, no I/O).
- `SelectShortHighlights` — the LLM use case; tested with a fake `LLMPort` so no
  network is touched. It must degrade to an empty selection on bad input.
"""
from __future__ import annotations

import json

import pytest

from videocreator.application.use_cases.shorts_planning import SelectShortHighlights
from videocreator.domain.entities import Scene
from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import PlatformRule
from videocreator.shared.ids import SceneId


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


def _scenes(n: int, dur: float = 8.0) -> list[Scene]:
    return [
        Scene(
            id=SceneId(f"scn_{i}"),
            index=i,
            visual_prompt=f"vp{i}",
            audio_text=f"line {i}",
            duration_s=dur,
            raw={"narrative_phase": "climax", "mood": "exciting"},
        )
        for i in range(n)
    ]


class _FakeLLM:
    """Returns a canned JSON string; records the prompt it was asked."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.prompts: list[str] = []

    async def complete(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


# ---- plan_montage (pure) --------------------------------------------------
def test_montage_maps_indices_to_source_offsets() -> None:
    # 5 scenes of 10s each → offsets 0,10,20,30,40
    planner = ShortPlanner()
    timeline = planner.plan_montage(
        scene_durations=[10.0] * 5, selected_indices=[0, 2, 4], rule=_rule()
    )
    starts = [s.source_start_s for s in timeline.segments]
    assert starts == [0.0, 20.0, 40.0]
    assert timeline.total_duration_s == pytest.approx(30.0)
    assert (timeline.width, timeline.height) == (1080, 1920)


def test_montage_clamps_total_to_platform_budget() -> None:
    # 10 scenes × 10s, pick all → must trim to the 60s ceiling
    planner = ShortPlanner()
    timeline = planner.plan_montage(
        scene_durations=[10.0] * 10,
        selected_indices=list(range(10)),
        rule=_rule(max_duration_s=60.0),
    )
    assert timeline.total_duration_s == pytest.approx(60.0)


def test_montage_dedupes_and_ignores_out_of_range() -> None:
    planner = ShortPlanner()
    timeline = planner.plan_montage(
        scene_durations=[10.0, 10.0, 10.0],
        selected_indices=[1, 1, 9, -3, 0],  # dupes + invalid
        rule=_rule(),
    )
    starts = [s.source_start_s for s in timeline.segments]
    assert starts == [10.0, 0.0]


def test_montage_empty_selection_yields_empty_timeline() -> None:
    timeline = ShortPlanner().plan_montage(
        scene_durations=[5.0, 5.0], selected_indices=[], rule=_rule()
    )
    assert timeline.is_empty


# ---- SelectShortHighlights (LLM use case) ---------------------------------
async def test_selector_parses_1based_numbers_to_indices() -> None:
    llm = _FakeLLM({"scene_numbers": [1, 3, 5], "hook_text": "Wait for it!"})
    selection = await SelectShortHighlights(llm=llm).execute(  # type: ignore[arg-type]
        scenes=_scenes(6), target_duration_s=30.0
    )
    assert selection.scene_indices == (0, 2, 4)
    assert selection.hook_text == "Wait for it!"


async def test_selector_empty_on_invalid_json() -> None:
    selection = await SelectShortHighlights(llm=_FakeLLM("not json")).execute(  # type: ignore[arg-type]
        scenes=_scenes(4), target_duration_s=20.0
    )
    assert selection.is_empty


async def test_selector_empty_on_no_scenes() -> None:
    llm = _FakeLLM({"scene_numbers": [1]})
    selection = await SelectShortHighlights(llm=llm).execute(  # type: ignore[arg-type]
        scenes=[], target_duration_s=20.0
    )
    assert selection.is_empty
    assert llm.prompts == []  # short-circuits before calling the LLM


async def test_selector_drops_out_of_range_numbers() -> None:
    llm = _FakeLLM({"scene_numbers": [2, 99, 0, 3]})  # 99 & 0 invalid (1-based)
    selection = await SelectShortHighlights(llm=llm).execute(  # type: ignore[arg-type]
        scenes=_scenes(4), target_duration_s=20.0
    )
    assert selection.scene_indices == (1, 2)
