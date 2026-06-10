"""Tests for §12 — format library, daily briefing, moderation, MCP bridge."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from videocreator.application.use_cases.content_moderation import (
    ModerateContentUseCase,
)
from videocreator.application.use_cases.daily_briefing import DailyBriefingUseCase
from videocreator.domain.value_objects import GenomeHook, ViralGenome
from videocreator.infrastructure.brain.mcp_client import McpToolBridge, mcp_available
from videocreator.infrastructure.brain.tools import ToolRegistry
from videocreator.infrastructure.vector.format_library import FormatLibrary


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def _genome(format_id: str = "") -> ViralGenome:
    return ViralGenome(
        format_id=format_id,
        hook=GenomeHook(type="visual_pattern_interrupt"),
        structure=(),
        why_it_works="expectation subversion",
    )


def _vec(direction: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[direction] = 1.0
    return v


class TestFormatLibrary:
    def test_new_genome_creates_format(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        fid = lib.add_genome(_genome(), _vec(0))
        assert fid == "format-0001"
        assert len(lib.list_formats()) == 1

    def test_similar_genome_clusters(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        fid1 = lib.add_genome(_genome(), _vec(0))
        fid2 = lib.add_genome(_genome(), _vec(0))  # identical vector → same cluster
        assert fid1 == fid2
        record = lib.get(fid1)
        assert record is not None and len(record.sightings) == 2

    def test_distinct_genome_new_format(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        fid1 = lib.add_genome(_genome(), _vec(0))
        fid2 = lib.add_genome(_genome(), _vec(1))  # orthogonal → new format
        assert fid1 != fid2
        assert len(lib.list_formats()) == 2

    def test_burned_after_14_days_vetoed(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        old = time.time() - 20 * 86400
        fid = lib.add_genome(_genome(), _vec(0), now=old)
        assert fid in lib.vetoed_ids()
        assert lib.emerging() == []

    def test_recent_format_emerging(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        lib.add_genome(_genome(), _vec(0))
        emerging = lib.emerging()
        assert len(emerging) == 1
        assert emerging[0].adoption_rate() > 0

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        lib = FormatLibrary(tmp_path, dim=8)
        fid = lib.add_genome(_genome(), _vec(0), niche="ai")
        lib2 = FormatLibrary(tmp_path, dim=8)
        record = lib2.get(fid)
        assert record is not None
        assert record.niches == ["ai"]
        # clustering still works against the reloaded index
        assert lib2.add_genome(_genome(), _vec(0)) == fid


class TestDailyBriefing:
    @pytest.mark.asyncio
    async def test_composes_all_sections(self) -> None:
        async def sounds(niche: str) -> list[dict]:
            return [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}, {"id": "s4"}]

        async def formats() -> list[dict]:
            return [{"format_id": "f1"}]

        async def trends(niche: str) -> list[str]:
            return ["term-a", "term-b"]

        uc = DailyBriefingUseCase(
            sounds_source=sounds, formats_source=formats, trends_source=trends)
        briefing = await uc.execute("pod1", niche="ai", max_sounds=3)
        assert len(briefing.sounds) == 3  # capped
        assert briefing.emerging_formats == ({"format_id": "f1"},)
        assert not briefing.is_empty

    @pytest.mark.asyncio
    async def test_dead_source_degrades(self) -> None:
        async def boom(niche: str) -> list[dict]:
            raise RuntimeError("scraper died")

        uc = DailyBriefingUseCase(sounds_source=boom)
        briefing = await uc.execute("pod1")
        assert briefing.sounds == ()
        assert briefing.is_empty

    @pytest.mark.asyncio
    async def test_no_sources_empty(self) -> None:
        briefing = await DailyBriefingUseCase().execute("pod1")
        assert briefing.is_empty


class TestModeration:
    @pytest.mark.asyncio
    async def test_clean_script_approved(self) -> None:
        uc = ModerateContentUseCase(FakeLLM([json.dumps({"flags": []})]))  # type: ignore[arg-type]
        result = await uc.execute("a wholesome cooking video")
        assert result.approved is True
        assert result.flags == ()

    @pytest.mark.asyncio
    async def test_high_severity_blocks(self) -> None:
        resp = json.dumps({"flags": [
            {"category": "medical_claim", "severity": "high",
             "detail": "cures cancer claim"}]})
        uc = ModerateContentUseCase(FakeLLM([resp]))  # type: ignore[arg-type]
        result = await uc.execute("this tea cures cancer")
        assert result.approved is False
        assert result.flags[0].category == "medical_claim"

    @pytest.mark.asyncio
    async def test_low_severity_approves_with_flags(self) -> None:
        resp = json.dumps({"flags": [
            {"category": "platform_policy", "severity": "low", "detail": "edgy"}]})
        uc = ModerateContentUseCase(FakeLLM([resp]))  # type: ignore[arg-type]
        result = await uc.execute("mildly edgy joke")
        assert result.approved is True
        assert len(result.flags) == 1

    @pytest.mark.asyncio
    async def test_unparseable_fails_closed(self) -> None:
        uc = ModerateContentUseCase(FakeLLM(["not json at all"]))  # type: ignore[arg-type]
        result = await uc.execute("anything")
        assert result.approved is False
        assert result.flags[0].severity == "high"


class _FakeMcpTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"does {name}"
        self.inputSchema = {"type": "object", "properties": {}}


class _FakeListing:
    def __init__(self, tools: list[_FakeMcpTool]) -> None:
        self.tools = tools


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeSession:
    def __init__(self) -> None:
        self.called_with: tuple[str, dict] | None = None

    async def list_tools(self) -> _FakeListing:
        return _FakeListing([_FakeMcpTool("web_search"), _FakeMcpTool("fetch")])

    async def call_tool(self, name: str, arguments: dict) -> _FakeResult:
        self.called_with = (name, arguments)
        return _FakeResult(f"result of {name}")


class TestMcpBridge:
    def test_available_flag_is_bool(self) -> None:
        assert isinstance(mcp_available(), bool)

    @pytest.mark.asyncio
    async def test_loads_namespaced_tools(self) -> None:
        registry = ToolRegistry()
        bridge = McpToolBridge("search", _FakeSession())
        count = await bridge.load_tools(registry)
        assert count == 2
        assert "search.web_search" in registry.names

    @pytest.mark.asyncio
    async def test_tool_call_flattens_text_content(self) -> None:
        registry = ToolRegistry()
        session = _FakeSession()
        await McpToolBridge("search", session).load_tools(registry)
        tool = registry.get("search.web_search")
        assert tool is not None
        result = await tool.fn(query="memes this week")
        assert result == "result of web_search"
        assert session.called_with == ("web_search", {"query": "memes this week"})

    @pytest.mark.asyncio
    async def test_dead_session_returns_zero(self) -> None:
        class DeadSession:
            async def list_tools(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("gone")

        registry = ToolRegistry()
        count = await McpToolBridge("dead", DeadSession()).load_tools(registry)
        assert count == 0
