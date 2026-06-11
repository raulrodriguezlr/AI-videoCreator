"""Tests for §3.3 scene recreation — fair-use, planner, trend match, DAG."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.scene_recreation import (
    FairUseAdvisorUseCase,
    PlanSceneRecreationUseCase,
    SceneTrendMatchUseCase,
    build_recreation_dag,
)


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def _fair_use_json(risk: str = "low") -> str:
    return json.dumps({"closeness": 0.3, "transformative": 0.8,
                       "risk": risk, "guidance": "change the dialogue"})


def _plan_json() -> str:
    return json.dumps({
        "title": "Invoice-time",
        "v2v_prompt": "office worker dodging flying invoices in slow motion",
        "reference_description": "rooftop bullet-time framing",
        "beats": [
            {"beat": "setup", "duration_s": 2.0, "description": "boss appears"},
            {"beat": "payoff", "duration_s": 1.5, "description": "dodge"},
        ],
        "audio_note": "own voiceover, tense synth",
    })


class TestFairUseAdvisor:
    @pytest.mark.asyncio
    async def test_parses_assessment(self) -> None:
        uc = FairUseAdvisorUseCase(FakeLLM([_fair_use_json()]))  # type: ignore[arg-type]
        result = await uc.execute(original="matrix scene", twist="invoices")
        assert result.risk == "low"
        assert result.requires_confirmation is False

    @pytest.mark.asyncio
    async def test_high_risk_requires_confirmation(self) -> None:
        uc = FairUseAdvisorUseCase(FakeLLM([_fair_use_json("high")]))  # type: ignore[arg-type]
        result = await uc.execute(original="x", twist="y")
        assert result.requires_confirmation is True

    @pytest.mark.asyncio
    async def test_unparseable_fails_closed_to_high(self) -> None:
        uc = FairUseAdvisorUseCase(FakeLLM(["garbage"]))  # type: ignore[arg-type]
        result = await uc.execute(original="x", twist="y")
        assert result.risk == "high"
        assert result.requires_confirmation is True

    @pytest.mark.asyncio
    async def test_invalid_risk_value_rejected_then_retried(self) -> None:
        bad = json.dumps({"closeness": 0.5, "transformative": 0.5,
                          "risk": "extreme", "guidance": ""})
        llm = FakeLLM([bad, _fair_use_json("medium")])
        uc = FairUseAdvisorUseCase(llm)  # type: ignore[arg-type]
        result = await uc.execute(original="x", twist="y")
        assert result.risk == "medium"
        assert llm.calls == 2


class TestPlanRecreation:
    @pytest.mark.asyncio
    async def test_full_plan_with_fair_use(self) -> None:
        llm = FakeLLM([_fair_use_json(), _plan_json()])
        uc = PlanSceneRecreationUseCase(llm)  # type: ignore[arg-type]
        plan = await uc.execute(original="matrix", niche="finance", twist="invoices")
        assert plan.title == "Invoice-time"
        assert len(plan.beats) == 2
        assert plan.fair_use.risk == "low"
        assert "voiceover" in plan.audio_note

    @pytest.mark.asyncio
    async def test_plan_without_beats_rejected(self) -> None:
        empty = json.dumps({"title": "x", "v2v_prompt": "y", "beats": [],
                            "audio_note": ""})
        llm = FakeLLM([_fair_use_json(), empty])
        uc = PlanSceneRecreationUseCase(llm)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute(original="m", niche="f", twist="i")


class TestTrendMatch:
    @pytest.mark.asyncio
    async def test_matches_candidates(self) -> None:
        resp = json.dumps([{"term": "bullet time", "scene": "The Matrix rooftop",
                            "why_trending": "anniversary"}])
        uc = SceneTrendMatchUseCase(FakeLLM([resp]))  # type: ignore[arg-type]
        result = await uc.execute(["bullet time", "recipe pasta"])
        assert len(result) == 1
        assert result[0].scene == "The Matrix rooftop"

    @pytest.mark.asyncio
    async def test_empty_terms_short_circuits(self) -> None:
        llm = FakeLLM(["should not be called"])
        uc = SceneTrendMatchUseCase(llm)  # type: ignore[arg-type]
        assert await uc.execute([]) == []
        assert llm.calls == 0

    @pytest.mark.asyncio
    async def test_unparseable_returns_empty(self) -> None:
        uc = SceneTrendMatchUseCase(FakeLLM(["not json"]))  # type: ignore[arg-type]
        assert await uc.execute(["term"]) == []


class TestRecreationDag:
    def test_low_risk_no_gate(self) -> None:
        spec = build_recreation_dag("ep1", risk="low")
        ids = {n.id for n in spec.nodes}
        assert "fair-use-gate" not in ids
        by_id = {n.id: n for n in spec.nodes}
        assert by_id["v2v"].depends_on == ("plan",)

    def test_high_risk_inserts_blocking_gate(self) -> None:
        spec = build_recreation_dag("ep1", risk="high")
        by_id = {n.id: n for n in spec.nodes}
        assert "fair-use-gate" in by_id
        assert by_id["v2v"].depends_on == ("fair-use-gate",)
        assert by_id["fair-use-gate"].max_retries == 0

    def test_dag_is_valid_and_composes(self) -> None:
        spec = build_recreation_dag("ep1", risk="medium")
        order = [n.id for n in spec.topo_order()]
        assert order.index("compose") > order.index("v2v")
        assert order.index("compose") > order.index("voice")
