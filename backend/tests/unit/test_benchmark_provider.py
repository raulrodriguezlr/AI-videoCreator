"""Tests for benchmark harness — fake LLM judge, no CLIP/OCR deps."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from videocreator.application.use_cases.benchmark_provider import (
    BenchmarkPrompt,
    BenchmarkProviderUseCase,
    PromptScore,
    Scorecard,
    load_prompts,
    ocr_match_score,
)

PROMPTS_JSON = Path(__file__).resolve().parents[2] / "assets" / "benchmark" / "prompts.json"


class FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        return self._response


class TestPromptSuite:
    def test_loads_suite(self) -> None:
        prompts = load_prompts(PROMPTS_JSON)
        assert len(prompts) == 20
        dims = {p.dimension for p in prompts}
        assert dims == {"motion", "faces", "text_render", "physics", "consistency"}

    def test_text_prompts_have_expected_text(self) -> None:
        prompts = load_prompts(PROMPTS_JSON)
        for p in prompts:
            if p.dimension == "text_render":
                assert p.expected_text


class TestOcrScore:
    def test_full_match(self) -> None:
        assert ocr_match_score("OPEN 24 HOURS neon", "OPEN 24 HOURS") == 1.0

    def test_partial_match(self) -> None:
        assert ocr_match_score("OPEN sign visible", "OPEN 24 HOURS") == pytest.approx(1 / 3)

    def test_no_match(self) -> None:
        assert ocr_match_score("nothing here", "MAIN STREET") == 0.0

    def test_case_and_punct_insensitive(self) -> None:
        assert ocr_match_score("main street!", "MAIN STREET") == 1.0


class TestBlending:
    def test_all_metrics(self) -> None:
        s = PromptScore(prompt_id="x", dimension="text_render",
                        clip_score=0.8, ocr_score=1.0, judge_score=0.6)
        expected = (0.3 * 0.8 + 0.2 * 1.0 + 0.5 * 0.6) / 1.0
        assert s.blended == pytest.approx(expected)

    def test_judge_only_renormalizes(self) -> None:
        s = PromptScore(prompt_id="x", dimension="motion", judge_score=0.7)
        assert s.blended == pytest.approx(0.7)

    def test_empty_is_zero(self) -> None:
        assert PromptScore(prompt_id="x", dimension="motion").blended == 0.0


class TestScorecard:
    def test_by_dimension_and_overall(self) -> None:
        card = Scorecard(provider_id="p1", scores=[
            PromptScore(prompt_id="a", dimension="motion", judge_score=0.8),
            PromptScore(prompt_id="b", dimension="motion", judge_score=0.6),
            PromptScore(prompt_id="c", dimension="faces", judge_score=1.0),
        ])
        dims = card.by_dimension()
        assert dims["motion"] == pytest.approx(0.7)
        assert dims["faces"] == pytest.approx(1.0)
        assert card.overall == pytest.approx(0.85)

    def test_empty_scorecard(self) -> None:
        assert Scorecard(provider_id="p").overall == 0.0


class TestJudge:
    @pytest.mark.asyncio
    async def test_score_prompt_with_judge(self) -> None:
        llm = FakeLLM(json.dumps({"adherence": 8, "artifacts": 9, "coherence": 7}))
        uc = BenchmarkProviderUseCase(llm)  # type: ignore[arg-type]
        bp = BenchmarkPrompt(id="m1", dimension="motion", prompt="a test")
        score = await uc.score_prompt(bp, frame_descriptions=["frame 1", "frame 2"])
        assert score.judge_score == pytest.approx(24 / 30)

    @pytest.mark.asyncio
    async def test_judge_parse_failure_gives_none(self) -> None:
        llm = FakeLLM("not json")
        uc = BenchmarkProviderUseCase(llm)  # type: ignore[arg-type]
        bp = BenchmarkPrompt(id="m1", dimension="motion", prompt="a test")
        score = await uc.score_prompt(bp, frame_descriptions=["f"])
        assert score.judge_score is None

    @pytest.mark.asyncio
    async def test_ocr_applied_when_expected_text(self) -> None:
        llm = FakeLLM(json.dumps({"adherence": 5, "artifacts": 5, "coherence": 5}))
        uc = BenchmarkProviderUseCase(llm)  # type: ignore[arg-type]
        bp = BenchmarkPrompt(id="t1", dimension="text_render",
                             prompt="sign", expected_text="MONDAY")
        score = await uc.score_prompt(bp, frame_descriptions=["f"], ocr_text="monday cup")
        assert score.ocr_score == 1.0
