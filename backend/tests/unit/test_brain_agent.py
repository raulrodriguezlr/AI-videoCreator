"""Tests for BrainAgent loop and ToolRegistry — fake LLM."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.infrastructure.brain.agent import BrainAgent
from videocreator.infrastructure.brain.tools import Tool, ToolRegistry


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._idx = 0

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


async def _echo_tool(text: str = "") -> dict[str, str]:
    return {"echo": text}


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="Echo back text",
        json_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        fn=_echo_tool,
    ))
    return reg


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        reg = _registry()
        assert reg.get("echo") is not None
        assert len(reg) == 1

    def test_duplicate_rejected(self) -> None:
        reg = _registry()
        with pytest.raises(ValueError, match="already registered"):
            reg.register(Tool(name="echo", description="x", json_schema={}, fn=_echo_tool))

    def test_schemas_shape(self) -> None:
        reg = _registry()
        schemas = reg.schemas
        assert schemas[0]["name"] == "echo"
        assert "parameters" in schemas[0]


class TestBrainAgent:
    @pytest.mark.asyncio
    async def test_direct_answer(self) -> None:
        llm = FakeLLM([json.dumps({"answer": "done"})])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, trace = await agent.run("test goal")
        assert answer == "done"
        assert trace[-1].kind == "answer"

    @pytest.mark.asyncio
    async def test_tool_call_then_answer(self) -> None:
        llm = FakeLLM([
            json.dumps({"tool": "echo", "args": {"text": "hola"}}),
            json.dumps({"answer": "echoed hola"}),
        ])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, trace = await agent.run("echo something")
        assert answer == "echoed hola"
        assert trace[0].kind == "tool_call"
        assert trace[0].tool == "echo"
        assert "hola" in (trace[0].result or "")

    @pytest.mark.asyncio
    async def test_unknown_tool_recovers(self) -> None:
        llm = FakeLLM([
            json.dumps({"tool": "nope", "args": {}}),
            json.dumps({"answer": "recovered"}),
        ])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, trace = await agent.run("goal")
        assert answer == "recovered"
        assert trace[0].kind == "error"

    @pytest.mark.asyncio
    async def test_invalid_json_recovers(self) -> None:
        llm = FakeLLM([
            "not json at all",
            json.dumps({"answer": "ok"}),
        ])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, _ = await agent.run("goal")
        assert answer == "ok"

    @pytest.mark.asyncio
    async def test_max_steps(self) -> None:
        llm = FakeLLM([json.dumps({"tool": "echo", "args": {"text": "loop"}})])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, trace = await agent.run("goal", max_steps=3)
        assert "max_steps" in answer
        assert len(trace) == 3

    @pytest.mark.asyncio
    async def test_tool_exception_captured(self) -> None:
        async def _boom() -> None:
            raise RuntimeError("kaput")

        reg = ToolRegistry()
        reg.register(Tool(name="boom", description="fails", json_schema={}, fn=_boom))
        llm = FakeLLM([
            json.dumps({"tool": "boom", "args": {}}),
            json.dumps({"answer": "handled"}),
        ])
        agent = BrainAgent(llm, reg)  # type: ignore[arg-type]
        answer, trace = await agent.run("goal")
        assert answer == "handled"
        assert "kaput" in (trace[0].result or "")

    @pytest.mark.asyncio
    async def test_markdown_fenced_json(self) -> None:
        llm = FakeLLM(['```json\n{"answer": "fenced"}\n```'])
        agent = BrainAgent(llm, _registry())  # type: ignore[arg-type]
        answer, _ = await agent.run("goal")
        assert answer == "fenced"
