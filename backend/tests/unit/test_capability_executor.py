"""Tests for the capability executor — handler registry + SDK fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from videocreator.domain.value_objects import DagNode, DagSpec
from videocreator.infrastructure.queue.capability_executor import CapabilityExecutor
from videocreator.infrastructure.queue.dag_executor import (
    DagExecutor,
    DagRun,
    NodeState,
)


class FakeLLM:
    async def complete(self, prompt: str, **kwargs: Any) -> str:
        return f"llm-output for: {prompt[:30]}"


@dataclass
class _FakeGenResult:
    video_bytes: bytes = b"\x00\x01"
    duration_s: float = 5.0
    width: int = 1080
    height: int = 1920
    metadata: dict = field(default_factory=dict)


class _FakeAdapter:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    async def generate(self, request: Any) -> _FakeGenResult:
        if self._fail:
            raise RuntimeError("boom")
        return _FakeGenResult()


class _FakeLoaded:
    def __init__(self, pid: str, fail: bool = False) -> None:
        self.manifest = type("M", (), {"id": pid})()
        self.adapter = _FakeAdapter(fail)


class _FakeRegistry:
    def __init__(self, loaded: list[_FakeLoaded]) -> None:
        self._loaded = loaded

    def find(self, capability: str, **kw: Any) -> list[_FakeLoaded]:
        return self._loaded


def _node(capability: str, **params: Any) -> DagNode:
    return DagNode(id="n1", capability=capability, params=params)


class TestHandlers:
    @pytest.mark.asyncio
    async def test_llm_text_handler(self) -> None:
        ex = CapabilityExecutor(FakeLLM())  # type: ignore[arg-type]
        result = await ex(_node("llm_text", task="write a thread"), {})
        assert "llm-output" in result

    @pytest.mark.asyncio
    async def test_load_master_passthrough(self) -> None:
        ex = CapabilityExecutor(FakeLLM())  # type: ignore[arg-type]
        result = await ex(_node("load_master", episode_id="ep1"), {})
        assert result == {"episode_id": "ep1"}

    @pytest.mark.asyncio
    async def test_custom_handler_registration(self) -> None:
        ex = CapabilityExecutor(FakeLLM())  # type: ignore[arg-type]

        async def custom(node: DagNode, upstream: dict) -> str:
            return "custom-done"

        ex.register("my_cap", custom)
        assert await ex(_node("my_cap"), {}) == "custom-done"
        assert "my_cap" in ex.capabilities

    @pytest.mark.asyncio
    async def test_unknown_capability_without_registry_raises(self) -> None:
        ex = CapabilityExecutor(FakeLLM())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="no handler"):
            await ex(_node("text_to_video", prompt="x"), {})


class TestSdkFallback:
    @pytest.mark.asyncio
    async def test_provider_resolves_capability(self) -> None:
        registry = _FakeRegistry([_FakeLoaded("ltx")])
        ex = CapabilityExecutor(FakeLLM(), provider_registry=registry)  # type: ignore[arg-type]
        result = await ex(_node("text_to_video", prompt="a cat", duration_s=5), {})
        assert result["provider"] == "ltx"
        assert result["bytes"] == 2

    @pytest.mark.asyncio
    async def test_fallback_chain_on_provider_failure(self) -> None:
        registry = _FakeRegistry([_FakeLoaded("bad", fail=True), _FakeLoaded("good")])
        ex = CapabilityExecutor(FakeLLM(), provider_registry=registry)  # type: ignore[arg-type]
        result = await ex(_node("text_to_video", prompt="x"), {})
        assert result["provider"] == "good"

    @pytest.mark.asyncio
    async def test_no_provider_for_capability_raises(self) -> None:
        ex = CapabilityExecutor(FakeLLM(), provider_registry=_FakeRegistry([]))  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="no provider declares"):
            await ex(_node("video_to_video", prompt="x"), {})

    @pytest.mark.asyncio
    async def test_prompt_falls_back_to_upstream_text(self) -> None:
        registry = _FakeRegistry([_FakeLoaded("p")])
        ex = CapabilityExecutor(FakeLLM(), provider_registry=registry)  # type: ignore[arg-type]
        result = await ex(_node("text_to_video"), {"plan": "a dog surfing"})
        assert result["provider"] == "p"


class TestEndToEndRun:
    @pytest.mark.asyncio
    async def test_full_dag_through_capability_executor(self) -> None:
        ex = CapabilityExecutor(FakeLLM())  # type: ignore[arg-type]
        spec = DagSpec(nodes=(
            DagNode(id="master", capability="load_master", params={"episode_id": "e"}),
            DagNode(id="thread", capability="llm_text",
                    params={"task": "thread"}, depends_on=("master",)),
        ))
        run = await DagExecutor(ex).run(DagRun(run_id="r", spec=spec))
        assert run.is_complete and not run.has_failures
        assert run.node_states["thread"].state == NodeState.DONE
