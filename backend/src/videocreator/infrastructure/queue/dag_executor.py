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

    def __init__(self, node_executor: NodeExecutor) -> None:
        self._execute_node = node_executor

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
                        self._handle_failure(run, node, result)
                    else:
                        run.node_states[node.id].state = NodeState.DONE
                        run.node_states[node.id].result = result
                        log.info("dag.node.done", run_id=run.run_id, node=node.id)

        return run

    async def _run_wave(
        self, run: DagRun, nodes: list[DagNode],
    ) -> list[tuple[DagNode, Any]]:
        for node in nodes:
            run.node_states[node.id].state = NodeState.RUNNING

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

    def _handle_failure(self, run: DagRun, node: DagNode, error: Exception) -> None:
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
        else:
            ns.state = NodeState.FAILED
            ns.error = str(error)
            log.error(
                "dag.node.failed",
                run_id=run.run_id,
                node=node.id,
                error=str(error),
            )


__all__ = [
    "DagDeadlockError",
    "DagExecutor",
    "DagRun",
    "NodeExecutor",
    "NodeResult",
    "NodeState",
]
