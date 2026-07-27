"""Tests for the copyright screener (pure) and the cached CopyrightGuard."""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.application.use_cases.copyright_guard import CopyrightGuard
from videocreator.domain.services.copyright_screen import (
    CopyrightScreen,
    build_prompt,
    parse_result,
)


# ---- Pure screener ---------------------------------------------------------
class TestParse:
    def test_real_person_is_risky(self) -> None:
        screen = parse_result(
            '{"has_real_people": true, "real_people": ["Cristiano Ronaldo"], '
            '"copyrighted_characters": [], "notes": "athlete"}'
        )
        assert screen.has_real_people is True
        assert screen.real_people == ("Cristiano Ronaldo",)
        assert screen.risky is True

    def test_copyrighted_character_is_risky(self) -> None:
        screen = parse_result(
            '{"has_real_people": false, "real_people": [], '
            '"copyrighted_characters": ["Mickey Mouse"]}'
        )
        assert screen.risky is True

    def test_original_content_is_safe(self) -> None:
        screen = parse_result(
            '{"has_real_people": false, "real_people": [], '
            '"copyrighted_characters": []}'
        )
        assert screen.risky is False

    def test_tolerates_code_fences(self) -> None:
        raw = '```json\n{"has_real_people": false, "real_people": [], ' \
              '"copyrighted_characters": []}\n```'
        screen = parse_result(raw)
        assert screen.risky is False

    def test_tolerates_surrounding_prose(self) -> None:
        raw = 'Sure, here is the result:\n{"has_real_people": true, ' \
              '"real_people": ["Elon Musk"], "copyrighted_characters": []}\nDone.'
        screen = parse_result(raw)
        assert screen.has_real_people is True

    def test_garbage_defaults_to_safe(self) -> None:
        screen = parse_result("not json at all")
        assert screen.risky is False
        assert "parse failed" in screen.notes

    def test_build_prompt_includes_script(self) -> None:
        assert "Cristiano" in build_prompt("Una historia sobre Cristiano")


# ---- Cached guard ----------------------------------------------------------
class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def complete(self, prompt: str, *, model=None, response_schema=None,
                       temperature: float = 0.7) -> str:
        self.calls += 1
        return self.reply


_RISKY = '{"has_real_people": true, "real_people": ["Cristiano Ronaldo"], ' \
         '"copyrighted_characters": [], "notes": "x"}'


@pytest.mark.asyncio
async def test_first_call_runs_llm_then_caches(tmp_path: Path) -> None:
    llm = FakeLLM(_RISKY)
    guard = CopyrightGuard(llm, tmp_path)
    screen, cached = await guard.screen("guion con Cristiano Ronaldo")
    assert cached is False
    assert llm.calls == 1
    assert screen.risky is True
    # second call with identical text → cache hit, no new LLM call
    screen2, cached2 = await guard.screen("guion con Cristiano Ronaldo")
    assert cached2 is True
    assert llm.calls == 1
    assert screen2.risky is True


@pytest.mark.asyncio
async def test_force_bypasses_cache(tmp_path: Path) -> None:
    llm = FakeLLM(_RISKY)
    guard = CopyrightGuard(llm, tmp_path)
    await guard.screen("texto")
    _, cached = await guard.screen("texto", force=True)
    assert cached is False
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_different_text_misses_cache(tmp_path: Path) -> None:
    llm = FakeLLM(_RISKY)
    guard = CopyrightGuard(llm, tmp_path)
    await guard.screen("texto A")
    await guard.screen("texto B")
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_corrupt_cache_triggers_rerun(tmp_path: Path) -> None:
    llm = FakeLLM(_RISKY)
    guard = CopyrightGuard(llm, tmp_path)
    screen, _ = await guard.screen("texto")
    # corrupt the single cache file
    cache_file = next(tmp_path.glob("*.json"))
    cache_file.write_text("{ broken", encoding="utf-8")
    _, cached = await guard.screen("texto")
    assert cached is False
    assert llm.calls == 2


def test_screen_roundtrips_dict() -> None:
    s = CopyrightScreen(has_real_people=True, real_people=("A",),
                        copyrighted_characters=("B",), notes="n")
    assert CopyrightScreen.from_dict(s.to_dict()) == s
