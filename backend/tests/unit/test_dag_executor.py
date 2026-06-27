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


# ---- Event hook + RunRegistry (§16.15) --------------------------------------
class TestExecutorEvents:
    @pytest.mark.asyncio
    async def test_emits_lifecycle_events(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(run_id: str, event: dict[str, Any]) -> None:
            events.append(event)

        async def ok(node: DagNode, upstream: dict[str, Any]) -> str:
            return "ok"

        spec = DagSpec(nodes=(
            DagNode(id="a", capability="x"),
            DagNode(id="b", capability="x", depends_on=("a",)),
        ))
        executor = DagExecutor(ok, on_event=on_event)
        await executor.run(DagRun(run_id="r1", spec=spec))

        kinds = [e["event"] for e in events]
        assert kinds.count("node_running") == 2
        assert kinds.count("node_done") == 2
        assert kinds[-1] == "run_complete"
        assert events[-1]["failed"] is False

    @pytest.mark.asyncio
    async def test_emits_failure_and_cancel_events(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(run_id: str, event: dict[str, Any]) -> None:
            events.append(event)

        async def boom(node: DagNode, upstream: dict[str, Any]) -> str:
            if node.id == "a":
                raise RuntimeError("kaput")
            return "ok"

        spec = DagSpec(nodes=(
            DagNode(id="a", capability="x", max_retries=0),
            DagNode(id="b", capability="x", depends_on=("a",)),
        ))
        executor = DagExecutor(boom, on_event=on_event)
        run = await executor.run(DagRun(run_id="r2", spec=spec))

        kinds = [e["event"] for e in events]
        assert "node_failed" in kinds
        assert "node_cancelled" in kinds
        assert run.has_failures

    @pytest.mark.asyncio
    async def test_event_hook_exception_does_not_break_run(self) -> None:
        async def bad_hook(run_id: str, event: dict[str, Any]) -> None:
            raise RuntimeError("hook broken")

        async def ok(node: DagNode, upstream: dict[str, Any]) -> str:
            return "ok"

        spec = DagSpec(nodes=(DagNode(id="a", capability="x"),))
        executor = DagExecutor(ok, on_event=bad_hook)
        run = await executor.run(DagRun(run_id="r3", spec=spec))
        assert run.is_complete and not run.has_failures


class TestRunRegistry:
    def test_register_and_snapshot(self) -> None:
        from videocreator.infrastructure.queue.dag_executor import RunRegistry

        spec = DagSpec(nodes=(DagNode(id="a", capability="x"),))
        run = DagRun(run_id="r1", spec=spec)
        registry = RunRegistry()
        registry.register(run)

        snap = registry.snapshot("r1")
        assert snap is not None
        assert snap["run_id"] == "r1"
        assert snap["nodes"]["a"]["state"] == "pending"
        assert registry.get("r1") is run

    def test_unknown_run_is_none(self) -> None:
        from videocreator.infrastructure.queue.dag_executor import RunRegistry

        registry = RunRegistry()
        assert registry.get("nope") is None
        assert registry.snapshot("nope") is None

    def test_snapshot_surfaces_node_output_and_terminal_video(self) -> None:
        from videocreator.infrastructure.queue.dag_executor import RunRegistry

        spec = DagSpec(nodes=(
            DagNode(id="gen", capability="text_to_video"),
            DagNode(id="render", capability="compose_short", depends_on=("gen",)),
        ))
        run = DagRun(run_id="r2", spec=spec)
        # Simulate executor outputs landing on node states.
        run.node_states["gen"].result = {"paths": ["/api/v1/storage/x/frame.png"]}
        run.node_states["render"].result = {
            "video_url": "/api/v1/storage/x/final.mp4", "storage_key": "x/final.mp4",
        }
        registry = RunRegistry()
        registry.register(run)

        snap = registry.snapshot("r2")
        assert snap is not None
        # Terminal render node's video bubbles up to the top-level field.
        assert snap["video_url"] == "/api/v1/storage/x/final.mp4"
        # Every produced artifact is collected (image path + video).
        assert "/api/v1/storage/x/frame.png" in snap["artifacts"]
        assert "/api/v1/storage/x/final.mp4" in snap["artifacts"]
        # Per-node output is exposed and JSON-safe.
        assert snap["nodes"]["render"]["output"]["storage_key"] == "x/final.mp4"

    def test_snapshot_no_video_when_no_render(self) -> None:
        from videocreator.infrastructure.queue.dag_executor import RunRegistry

        spec = DagSpec(nodes=(DagNode(id="a", capability="llm_text"),))
        run = DagRun(run_id="r3", spec=spec)
        run.node_states["a"].result = "just a string, not a dict"
        registry = RunRegistry()
        registry.register(run)

        snap = registry.snapshot("r3")
        assert snap is not None
        assert snap["video_url"] is None
        assert snap["artifacts"] == []
        assert snap["nodes"]["a"]["output"] is None
