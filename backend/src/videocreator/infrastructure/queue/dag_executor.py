"""DAG Executor — runs a render pipeline as a directed acyclic graph.

Nodes with satisfied dependencies run in parallel via asyncio.gather.
State is tracked per-node so a crashed run can resume from where it stopped.
No external broker required — local-first by design.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from videocreator.domain.value_objects import DagNode, DagSpec
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class NodeState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class NodeResult:
    state: NodeState = NodeState.PENDING
    result: Any = None
    error: str | None = None
    retries_left: int = 2


NodeExecutor = Callable[[DagNode, dict[str, Any]], Awaitable[Any]]

#: Async progress hook: (run_id, event_dict). Feeds the SSE stream (§16.15).
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


def _safe_result(value: Any) -> Any:
    """Coerce an executor return value into a JSON-serialisable shape."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _safe_result(v) for k, v in value.items() if isinstance(k, str)}
    if isinstance(value, (list, tuple)):
        return [_safe_result(v) for v in value]
    return str(value)


class DagDeadlockError(Exception):
    """Raised when no nodes are ready but work remains."""


@dataclass
class DagRun:
    """Tracks execution state for one DAG run."""

    run_id: str
    spec: DagSpec
    node_states: dict[str, NodeResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for node in self.spec.nodes:
            if node.id not in self.node_states:
                self.node_states[node.id] = NodeResult(retries_left=node.max_retries)

    @property
    def pending_ids(self) -> set[str]:
        return {
            nid for nid, ns in self.node_states.items()
            if ns.state in (NodeState.PENDING, NodeState.RUNNING)
        }

    @property
    def is_complete(self) -> bool:
        return all(
            ns.state in (NodeState.DONE, NodeState.FAILED, NodeState.CANCELLED)
            for ns in self.node_states.values()
        )

    @property
    def has_failures(self) -> bool:
        return any(ns.state == NodeState.FAILED for ns in self.node_states.values())


class DagExecutor:
    """Execute a DagSpec by running ready nodes in parallel waves."""

    def __init__(
        self,
        node_executor: NodeExecutor,
        *,
        on_event: EventCallback | None = None,
    ) -> None:
        self._execute_node = node_executor
        self._on_event = on_event

    async def _emit(self, run: DagRun, event: str, **data: Any) -> None:
        if self._on_event is None:
            return
        try:
            await self._on_event(run.run_id, {"event": event, **data})
        except Exception:
            log.warning("dag.event_hook_failed", run_id=run.run_id, kind=event)

    async def run(self, run: DagRun) -> DagRun:
        by_id = {n.id: n for n in run.spec.nodes}

        while True:
            pending = run.pending_ids
            if not pending:
                break

            ready = [
                by_id[nid] for nid in pending
                if run.node_states[nid].state == NodeState.PENDING
                and all(
                    run.node_states[dep].state == NodeState.DONE
                    for dep in by_id[nid].depends_on
                )
            ]

            cancelled = [
                nid for nid in pending
                if run.node_states[nid].state == NodeState.PENDING
                and any(
                    run.node_states[dep].state in (NodeState.FAILED, NodeState.CANCELLED)
                    for dep in by_id[nid].depends_on
                )
            ]
            for nid in cancelled:
                run.node_states[nid].state = NodeState.CANCELLED
                log.info("dag.node.cancelled", run_id=run.run_id, node=nid)
                await self._emit(run, "node_cancelled", node=nid)

            if not ready and not cancelled:
                still_running = [
                    nid for nid in pending
                    if run.node_states[nid].state == NodeState.RUNNING
                ]
                if not still_running:
                    raise DagDeadlockError(
                        f"DAG run {run.run_id}: no ready nodes but work remains "
                        f"(pending: {pending})"
                    )
                break

            if ready:
                results = await self._run_wave(run, ready)
                for node, result in results:
                    if isinstance(result, Exception):
                        await self._handle_failure(run, node, result)
                    else:
                        run.node_states[node.id].state = NodeState.DONE
                        run.node_states[node.id].result = result
                        log.info("dag.node.done", run_id=run.run_id, node=node.id)
                        await self._emit(run, "node_done", node=node.id)

        await self._emit(run, "run_complete", failed=run.has_failures)
        return run

    async def _run_wave(
        self, run: DagRun, nodes: list[DagNode],
    ) -> list[tuple[DagNode, Any]]:
        for node in nodes:
            run.node_states[node.id].state = NodeState.RUNNING
            await self._emit(run, "node_running", node=node.id)

        upstream_results = {
            nid: ns.result
            for nid, ns in run.node_states.items()
            if ns.state == NodeState.DONE
        }

        tasks = [
            self._safe_execute(node, upstream_results)
            for node in nodes
        ]
        results = await asyncio.gather(*tasks)
        return list(zip(nodes, results))

    async def _safe_execute(
        self, node: DagNode, upstream: dict[str, Any],
    ) -> Any:
        try:
            return await self._execute_node(node, upstream)
        except Exception as e:
            return e

    async def _handle_failure(self, run: DagRun, node: DagNode, error: Exception) -> None:
        ns = run.node_states[node.id]
        if ns.retries_left > 0:
            ns.retries_left -= 1
            ns.state = NodeState.PENDING
            log.warning(
                "dag.node.retry",
                run_id=run.run_id,
                node=node.id,
                retries_left=ns.retries_left,
                error=str(error),
            )
            await self._emit(run, "node_retry", node=node.id,
                             retries_left=ns.retries_left)
        else:
            ns.state = NodeState.FAILED
            ns.error = str(error)
            log.error(
                "dag.node.failed",
                run_id=run.run_id,
                node=node.id,
                error=str(error),
            )
            await self._emit(run, "node_failed", node=node.id, error=str(error))


class RunRegistry:
    """In-memory registry of DAG runs — read-side for `/runs/{id}` (§16.15).

    Local-first: process-scoped. Server mode can swap this for a DB-backed
    registry behind the same three methods.
    """

    def __init__(self) -> None:
        self._runs: dict[str, DagRun] = {}

    def register(self, run: DagRun) -> None:
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> DagRun | None:
        return self._runs.get(run_id)

    def snapshot(self, run_id: str) -> dict[str, Any] | None:
        """JSON-safe view of a run's node states + produced artifacts.

        Each node carries its `output` (the executor's return value, made
        JSON-safe); `video_url` is the last node that produced a playable video
        (the terminal compose/render), and `artifacts` collects every video URL
        and image path across the run so the UI can show and download results
        instead of just a row of green badges.
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        video_url: str | None = None
        artifacts: list[str] = []
        # Iterate in spec order so `video_url` ends on the terminal render node.
        for node in run.spec.nodes:
            out = _safe_result(run.node_states[node.id].result)
            if isinstance(out, dict):
                if isinstance(out.get("video_url"), str):
                    video_url = out["video_url"]
                    artifacts.append(out["video_url"])
                for path in out.get("paths", []) or []:
                    if isinstance(path, str):
                        artifacts.append(path)
        return {
            "run_id": run.run_id,
            "is_complete": run.is_complete,
            "has_failures": run.has_failures,
            "video_url": video_url,
            "artifacts": artifacts,
            "nodes": {
                nid: {
                    "state": ns.state.value,
                    "error": ns.error,
                    "retries_left": ns.retries_left,
                    "output": _safe_result(ns.result) if isinstance(ns.result, dict) else None,
                }
                for nid, ns in run.node_states.items()
            },
        }


__all__ = [
    "DagDeadlockError",
    "DagExecutor",
    "DagRun",
    "EventCallback",
    "NodeExecutor",
    "NodeResult",
    "NodeState",
    "RunRegistry",
]
