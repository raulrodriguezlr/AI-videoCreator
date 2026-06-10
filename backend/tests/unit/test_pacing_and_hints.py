"""Tests for §3.1 pacing heuristics + §5 provider hints + §4.E visualizer."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.concept_visualizer import (
    ConceptVisualizerUseCase,
)
from videocreator.domain.services.pacing import analyze_pacing
from videocreator.domain.services.provider_hints import (
    format_suggestion,
    hint_for,
)


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


class TestPacing:
    def test_fast_meme_classification(self) -> None:
        report = analyze_pacing([1.0, 1.5, 1.2])
        assert report.classification == "fast_meme"
        assert report.suggested_durations_s == (1.0, 1.5, 1.2)

    def test_dialogue_heavy_tightens(self) -> None:
        report = analyze_pacing([6.0, 5.0, 3.0])
        assert report.classification == "dialogue_heavy"
        assert report.suggested_durations_s == (4.0, 4.0, 3.0)

    def test_balanced_untouched(self) -> None:
        report = analyze_pacing([3.0, 3.5, 2.5])
        assert report.classification == "balanced"
        assert report.suggested_durations_s == (3.0, 3.5, 2.5)

    def test_empty_script(self) -> None:
        report = analyze_pacing([])
        assert report.classification == "balanced"
        assert report.suggested_durations_s == ()


class TestProviderHints:
    def test_meme_never_veo(self) -> None:
        hint = hint_for("meme", duration_s=10)
        assert hint is not None
        assert hint.priorities[0] == "ltx"
        assert "veo" not in hint.priorities

    def test_story_switches_on_duration(self) -> None:
        short = hint_for("story", duration_s=45)
        long = hint_for("story", duration_s=400)
        assert short is not None and short.priorities[0] == "kling"
        assert long is not None and long.priorities[0] == "veo"

    def test_unknown_type_none(self) -> None:
        assert hint_for("vlog") is None

    def test_long_form_fallback_when_variant_missing(self) -> None:
        # meme has no long-form entry — falls back to the short-form hint
        hint = hint_for("meme", duration_s=999)
        assert hint is not None and hint.priorities[0] == "ltx"

    def test_suggestion_copy_includes_confirmation(self) -> None:
        hint = hint_for("meme", duration_s=10)
        assert hint is not None
        msg = format_suggestion(hint, current_provider="veo")
        assert msg is not None
        assert "ltx" in msg and "veo" in msg and "¿" in msg

    def test_no_suggestion_when_already_optimal(self) -> None:
        hint = hint_for("meme", duration_s=10)
        assert hint is not None
        assert format_suggestion(hint, current_provider="ltx") is None


def _metaphor_json() -> str:
    return json.dumps({
        "metaphor": "economy as a river of coins",
        "mappings": [{"abstract": "inflation", "visual": "gathering clouds"}],
        "video_prompt": "a river of golden coins flowing through a valley",
        "text_fallback": "ECONOMY = FLOW",
    })


class TestConceptVisualizer:
    @pytest.mark.asyncio
    async def test_returns_metaphor_with_fallback(self) -> None:
        uc = ConceptVisualizerUseCase(FakeLLM([_metaphor_json()]))  # type: ignore[arg-type]
        result = await uc.execute("the economy is money flow")
        assert result.text_fallback == "ECONOMY = FLOW"
        assert result.mappings == (("inflation", "gathering clouds"),)

    @pytest.mark.asyncio
    async def test_retry_then_success(self) -> None:
        llm = FakeLLM(["garbage", _metaphor_json()])
        uc = ConceptVisualizerUseCase(llm)  # type: ignore[arg-type]
        result = await uc.execute("entropy")
        assert llm.calls == 2
        assert result.metaphor

    @pytest.mark.asyncio
    async def test_raises_after_two_failures(self) -> None:
        uc = ConceptVisualizerUseCase(FakeLLM(["nope"]))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute("entropy")

    @pytest.mark.asyncio
    async def test_missing_fallback_rejected(self) -> None:
        incomplete = json.dumps({"metaphor": "x", "video_prompt": "y"})
        uc = ConceptVisualizerUseCase(FakeLLM([incomplete]))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute("entropy")
