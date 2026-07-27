"""Unit tests for GenerateNativeShortUseCase — fake LLM, no external calls."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.native_short import (
    GenerateNativeShortUseCase,
    _parse_structure,
)
from videocreator.domain.value_objects import ShortStructure


class FakeLLM:
    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_idx = 0

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        if self._responses:
            resp = self._responses[self._call_idx % len(self._responses)]
            self._call_idx += 1
            return resp
        return json.dumps(_valid_structure())


def _valid_structure() -> dict:
    return {
        "total_duration_s": 15,
        "segments": [
            {
                "role": "hook",
                "duration_s": 1.5,
                "visual_prompt": "Dramatic close-up of cat falling mid-air",
                "audio_text": "Why do cats ALWAYS land on their feet?",
                "sfx_vibe": "impact",
                "cut_style": "zoom_punch",
            },
            {
                "role": "body",
                "duration_s": 10,
                "visual_prompt": "Slow-motion cat righting reflex demonstration",
                "audio_text": "It's called the righting reflex",
                "sfx_vibe": "whoosh",
                "cut_style": "xfade",
            },
            {
                "role": "conclusion",
                "duration_s": 3.5,
                "visual_prompt": "Cat landing gracefully, looks at camera",
                "audio_text": "Follow for more animal science",
                "sfx_vibe": "none",
                "cut_style": "hard",
            },
        ],
        "music_vibe": "energetic",
        "caption_keywords": ["righting", "reflex"],
    }


@pytest.mark.asyncio
async def test_generates_structure() -> None:
    uc = GenerateNativeShortUseCase(llm=FakeLLM())  # type: ignore[arg-type]
    result = await uc.execute("Why cats land on their feet")
    assert isinstance(result, ShortStructure)
    assert len(result.segments) == 3
    assert result.total_duration_s == 15


@pytest.mark.asyncio
async def test_content_type_meme_uses_short_duration() -> None:
    uc = GenerateNativeShortUseCase(llm=FakeLLM())  # type: ignore[arg-type]
    result = await uc.execute("Cat vs cucumber", content_type="meme")
    assert isinstance(result, ShortStructure)


@pytest.mark.asyncio
async def test_custom_duration_override() -> None:
    uc = GenerateNativeShortUseCase(llm=FakeLLM())  # type: ignore[arg-type]
    result = await uc.execute("Topic", duration_s=45)
    assert isinstance(result, ShortStructure)


@pytest.mark.asyncio
async def test_retries_on_parse_failure() -> None:
    uc = GenerateNativeShortUseCase(
        llm=FakeLLM(responses=["not json", json.dumps(_valid_structure())]),  # type: ignore[arg-type]
    )
    result = await uc.execute("Topic with retry")
    assert isinstance(result, ShortStructure)
    assert len(result.segments) == 3


@pytest.mark.asyncio
async def test_raises_after_two_failures() -> None:
    uc = GenerateNativeShortUseCase(
        llm=FakeLLM(responses=["bad", "also bad"]),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="2 attempts"):
        await uc.execute("Doomed concept")


def test_parse_structure_strips_markdown_fences() -> None:
    raw = "```json\n" + json.dumps(_valid_structure()) + "\n```"
    result = _parse_structure(raw)
    assert result is not None
    assert len(result.segments) == 3


def test_parse_structure_returns_none_on_garbage() -> None:
    assert _parse_structure("not json at all") is None


def test_parse_structure_validates_schema() -> None:
    bad_data = json.dumps({"total_duration_s": 10, "segments": [{"role": "invalid_role"}]})
    assert _parse_structure(bad_data) is None
