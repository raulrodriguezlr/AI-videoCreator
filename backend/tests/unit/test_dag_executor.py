"""Tests for DAG value objects and executor."""
from __future__ import annotations

from typing import Any

import pytest

from videocreator.domain.value_objects import DagNode, DagSpec
from videocreator.infrastructure.queue.dag_executor import (
    DagDeadlockError,
    DagExecutor,
    DagRun,
    NodeState,
)


# ---- DagSpec validation tests ----------------------------------------------
class TestDagSpec:
    def test_valid_linear(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="tts"),
            DagNode(id="b", capability="t2v", depends_on=("a",)),
            DagNode(id="c", capability="compose", depends_on=("b",)),
        ))
        assert len(spec.nodes) == 3

    def test_valid_parallel(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="t2v"),
            DagNode(id="b", capability="t2v"),
            DagNode(id="c", capability="compose", depends_on=("a", "b")),
        ))
        order = spec.topo_order()
        ids = [n.id for n in order]
        assert ids.index("c") > ids.index("a")
        assert ids.index("c") > ids.index("b")

    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(ValueError, match="Duplicate"):
            DagSpec(nodes=(
                DagNode(id="a", capability="t2v"),
                DagNode(id="a", capability="tts"),
            ))

    def test_rejects_unknown_dependency(self) -> None:
        with pytest.raises(ValueError, match="unknown node"):
            DagSpec(nodes=(
                DagNode(id="a", capability="t2v", depends_on=("nonexistent",)),
            ))

    def test_rejects_cycle(self) -> None:
        with pytest.raises(ValueError, match="cycle"):
            DagSpec(nodes=(
                DagNode(id="a", capability="t2v", depends_on=("b",)),
                DagNode(id="b", capability="t2v", depends_on=("a",)),
            ))

    def test_topo_order_single(self) -> None:
        spec = DagSpec(nodes=(DagNode(id="x", capability="t2v"),))
        assert [n.id for n in spec.topo_order()] == ["x"]


# ---- DagExecutor tests ----------------------------------------------------
async def _ok_executor(node: DagNode, upstream: dict[str, Any]) -> str:
    return f"result_{node.id}"


async def _failing_executor(node: DagNode, upstream: dict[str, Any]) -> str:
    if node.id == "fail":
        raise RuntimeError("boom")
    return f"result_{node.id}"


call_count: dict[str, int] = {}


async def _counting_executor(node: DagNode, upstream: dict[str, Any]) -> str:
    call_count.setdefault(node.id, 0)
    call_count[node.id] += 1
    if node.id == "flaky" and call_count[node.id] <= 1:
        raise RuntimeError("flaky failure")
    return f"result_{node.id}"


class TestDagExecutor:
    @pytest.mark.asyncio
    async def test_linear_execution(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="tts"),
            DagNode(id="b", capability="t2v", depends_on=("a",)),
        ))
        run = DagRun(run_id="r1", spec=spec)
        executor = DagExecutor(_ok_executor)
        result = await executor.run(run)
        assert result.node_states["a"].state == NodeState.DONE
        assert result.node_states["b"].state == NodeState.DONE
        assert result.node_states["a"].result == "result_a"

    @pytest.mark.asyncio
    async def test_parallel_execution(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="t2v"),
            DagNode(id="b", capability="t2v"),
            DagNode(id="c", capability="compose", depends_on=("a", "b")),
        ))
        run = DagRun(run_id="r2", spec=spec)
        executor = DagExecutor(_ok_executor)
        result = await executor.run(run)
        assert all(
            result.node_states[nid].state == NodeState.DONE
            for nid in ["a", "b", "c"]
        )

    @pytest.mark.asyncio
    async def test_failure_cancels_dependents(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="fail", capability="t2v", max_retries=0),
            DagNode(id="downstream", capability="compose", depends_on=("fail",)),
        ))
        run = DagRun(run_id="r3", spec=spec)
        executor = DagExecutor(_failing_executor)
        result = await executor.run(run)
        assert result.node_states["fail"].state == NodeState.FAILED
        assert result.node_states["downstream"].state == NodeState.CANCELLED

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        global call_count
        call_count = {}
        spec = DagSpec(nodes=(
            DagNode(id="flaky", capability="t2v", max_retries=2),
        ))
        run = DagRun(run_id="r4", spec=spec)
        executor = DagExecutor(_counting_executor)
        result = await executor.run(run)
        assert result.node_states["flaky"].state == NodeState.DONE
        assert call_count["flaky"] == 2

    @pytest.mark.asyncio
    async def test_is_complete(self) -> None:
        spec = DagSpec(nodes=(DagNode(id="a", capability="t2v"),))
        run = DagRun(run_id="r5", spec=spec)
        assert not run.is_complete
        executor = DagExecutor(_ok_executor)
        result = await executor.run(run)
        assert result.is_complete

    @pytest.mark.asyncio
    async def test_has_failures(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="fail", capability="t2v", max_retries=0),
        ))
        run = DagRun(run_id="r6", spec=spec)
        executor = DagExecutor(_failing_executor)
        result = await executor.run(run)
        assert result.has_failures

    @pytest.mark.asyncio
    async def test_resume_skips_done(self) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="tts"),
            DagNode(id="b", capability="t2v", depends_on=("a",)),
        ))
        run = DagRun(run_id="r7", spec=spec)
        run.node_states["a"].state = NodeState.DONE
        run.node_states["a"].result = "cached_a"
        executor = DagExecutor(_ok_executor)
        result = await executor.run(run)
        assert result.node_states["a"].result == "cached_a"
        assert result.node_states["b"].state == NodeState.DONE

    @pytest.mark.asyncio
    async def test_empty_dag(self) -> None:
        spec = DagSpec(nodes=())
        run = DagRun(run_id="r8", spec=spec)
        executor = DagExecutor(_ok_executor)
        result = await executor.run(run)
        assert result.is_complete
