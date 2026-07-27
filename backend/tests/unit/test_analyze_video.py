"""Tests for AnalyzeVideoUseCase — fake LLM, no external calls."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.analyze_video import (
    AnalyzeVideoUseCase,
    _parse_genome,
)
from videocreator.domain.value_objects import ViralGenome


def _valid_genome() -> dict:
    return {
        "format_id": "expectation-subversion-v1",
        "hook": {
            "type": "visual_pattern_interrupt",
            "duration_s": 1.2,
            "text_overlay": "POV: ...",
        },
        "structure": [
            {
                "beat": "setup",
                "duration_s": 2.5,
                "audio": "trending_sound_x",
                "camera": "static_selfie",
            },
            {
                "beat": "punchline",
                "duration_s": 1.0,
                "sfx": "bass_drop",
                "cut_style": "hard_cut_zoom",
            },
        ],
        "captions": {"style": "word_by_word", "highlight": "yellow_bold_keyword"},
        "sound": {"id": "snd-1", "trending": True, "commercial_safe": False},
        "why_it_works": "expectation subversion + payoff before swipe",
        "remixability": 0.87,
        "decay_estimate": "1-2 weeks",
    }


class FakeLLM:
    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self._idx = 0

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        if self._responses:
            resp = self._responses[self._idx % len(self._responses)]
            self._idx += 1
            return resp
        return json.dumps(_valid_genome())


@pytest.mark.asyncio
async def test_extracts_genome() -> None:
    uc = AnalyzeVideoUseCase(llm=FakeLLM())  # type: ignore[arg-type]
    genome = await uc.execute(context="A cat knocks over a glass, slow-mo reaction")
    assert isinstance(genome, ViralGenome)
    assert genome.format_id == "expectation-subversion-v1"
    assert len(genome.structure) == 2
    assert genome.remixability == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_retries_on_bad_json() -> None:
    uc = AnalyzeVideoUseCase(
        llm=FakeLLM(responses=["garbage", json.dumps(_valid_genome())]),  # type: ignore[arg-type]
    )
    genome = await uc.execute(context="some video")
    assert genome.format_id == "expectation-subversion-v1"


@pytest.mark.asyncio
async def test_raises_after_two_failures() -> None:
    uc = AnalyzeVideoUseCase(llm=FakeLLM(responses=["bad", "worse"]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="2 attempts"):
        await uc.execute(context="doomed")


def test_parse_genome_strips_fences() -> None:
    raw = "```json\n" + json.dumps(_valid_genome()) + "\n```"
    g = _parse_genome(raw)
    assert g is not None
    assert g.hook.type == "visual_pattern_interrupt"


def test_parse_genome_rejects_invalid_schema() -> None:
    bad = json.dumps({"format_id": "x", "hook": {"type": "t"}, "remixability": 5.0})
    assert _parse_genome(bad) is None


def test_parse_genome_rejects_garbage() -> None:
    assert _parse_genome("not json") is None
