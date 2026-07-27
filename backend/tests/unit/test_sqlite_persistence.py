"""Tests for SQLite-backed cost ledger and DAG run store persistence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from videocreator.domain.services.capability_router import CostEntry
from videocreator.domain.value_objects import DagNode, DagSpec
from videocreator.infrastructure.persistence.sqlite_cost_ledger import SqliteCostLedger
from videocreator.infrastructure.persistence.sqlite_run_store import SqliteRunStore
from videocreator.infrastructure.queue.dag_executor import (
    DagExecutor,
    DagRun,
    NodeState,
)


# ---- SqliteCostLedger -------------------------------------------------------
class TestSqliteCostLedger:
    def test_record_and_entries_roundtrip(self, tmp_path: Path) -> None:
        ledger = SqliteCostLedger(tmp_path / "ledger.db")
        entry = CostEntry(
            provider_id="elevenlabs",
            capability="tts",
            units=120.0,
            unit_type="chars",
            cost_usd=0.05,
            timestamp=1000.0,
            episode_id="ep1",
        )
        ledger.record(entry)

        entries = ledger.entries
        assert len(entries) == 1
        got = entries[0]
        assert got.provider_id == "elevenlabs"
        assert got.capability == "tts"
        assert got.units == 120.0
        assert got.unit_type == "chars"
        assert got.cost_usd == 0.05
        assert got.timestamp == 1000.0
        assert got.episode_id == "ep1"

    def test_total_cost_filtered_by_episode_id(self, tmp_path: Path) -> None:
        ledger = SqliteCostLedger(tmp_path / "ledger.db")
        ledger.record(CostEntry(
            provider_id="a", capability="tts", units=1, unit_type="chars",
            cost_usd=1.0, timestamp=1.0, episode_id="ep1",
        ))
        ledger.record(CostEntry(
            provider_id="b", capability="t2v", units=1, unit_type="seconds",
            cost_usd=2.0, timestamp=2.0, episode_id="ep2",
        ))
        ledger.record(CostEntry(
            provider_id="a", capability="tts", units=1, unit_type="chars",
            cost_usd=0.5, timestamp=3.0, episode_id="ep1",
        ))

        assert ledger.total_cost(episode_id="ep1") == pytest.approx(1.5)
        assert ledger.total_cost(episode_id="ep2") == pytest.approx(2.0)
        assert ledger.total_cost() == pytest.approx(3.5)

    def test_check_budget_true_and_false(self, tmp_path: Path) -> None:
        ledger = SqliteCostLedger(tmp_path / "ledger.db")
        ledger.record(CostEntry(
            provider_id="a", capability="tts", units=1, unit_type="chars",
            cost_usd=4.0, timestamp=1.0, episode_id="ep1",
        ))

        assert ledger.check_budget(1.0, budget_usd=10.0) is True
        assert ledger.check_budget(10.0, budget_usd=10.0) is False
        # No budget set means always within budget.
        assert ledger.check_budget(1000.0, budget_usd=None) is True

    def test_persistence_across_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ledger.db"
        ledger1 = SqliteCostLedger(db_path)
        ledger1.record(CostEntry(
            provider_id="a", capability="tts", units=1, unit_type="chars",
            cost_usd=2.5, timestamp=1.0, episode_id="ep1",
        ))

        ledger2 = SqliteCostLedger(db_path)
        assert len(ledger2.entries) == 1
        assert ledger2.total_cost() == pytest.approx(2.5)


# ---- SqliteRunStore ----------------------------------------------------------
async def _ok_executor(node: DagNode, upstream: dict[str, Any]) -> str:
    return f"result_{node.id}"


class TestSqliteRunStore:
    def _make_run(self) -> DagRun:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="tts"),
            DagNode(id="b", capability="t2v", depends_on=("a",)),
            DagNode(id="c", capability="compose", depends_on=("b",)),
        ))
        run = DagRun(run_id="run-1", spec=spec)
        run.node_states["a"].state = NodeState.DONE
        run.node_states["b"].state = NodeState.FAILED
        run.node_states["b"].error = "boom"
        run.node_states["b"].retries_left = 0
        return run

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        store = SqliteRunStore(tmp_path / "runs.db")
        run = self._make_run()
        store.save(run)

        loaded = store.load("run-1")
        assert loaded is not None
        assert loaded.run_id == "run-1"
        assert [n.id for n in loaded.spec.nodes] == ["a", "b", "c"]

        assert loaded.node_states["a"].state == NodeState.DONE
        assert loaded.node_states["a"].result is None

        assert loaded.node_states["b"].state == NodeState.FAILED
        assert loaded.node_states["b"].error == "boom"
        assert loaded.node_states["b"].retries_left == 0

        assert loaded.node_states["c"].state == NodeState.PENDING

    def test_load_unknown_returns_none(self, tmp_path: Path) -> None:
        store = SqliteRunStore(tmp_path / "runs.db")
        assert store.load("nope") is None

    def test_list_ids(self, tmp_path: Path) -> None:
        store = SqliteRunStore(tmp_path / "runs.db")
        store.save(self._make_run())

        spec2 = DagSpec(nodes=(DagNode(id="x", capability="tts"),))
        run2 = DagRun(run_id="run-2", spec=spec2)
        store.save(run2)

        assert store.list_ids() == ["run-1", "run-2"]

    def test_delete(self, tmp_path: Path) -> None:
        store = SqliteRunStore(tmp_path / "runs.db")
        run = self._make_run()
        store.save(run)
        assert store.load("run-1") is not None

        store.delete("run-1")
        assert store.load("run-1") is None
        assert store.list_ids() == []

    @pytest.mark.asyncio
    async def test_resume_only_completes_pending_nodes(self, tmp_path: Path) -> None:
        spec = DagSpec(nodes=(
            DagNode(id="a", capability="tts"),
            DagNode(id="b", capability="t2v", depends_on=("a",)),
        ))
        run = DagRun(run_id="resume-1", spec=spec)
        run.node_states["a"].state = NodeState.DONE
        run.node_states["a"].result = "cached_a"

        store = SqliteRunStore(tmp_path / "runs.db")
        store.save(run)

        loaded = store.load("resume-1")
        assert loaded is not None
        assert loaded.node_states["a"].state == NodeState.DONE
        assert loaded.node_states["b"].state == NodeState.PENDING

        executor = DagExecutor(_ok_executor)
        result = await executor.run(loaded)

        assert result.node_states["a"].state == NodeState.DONE
        assert result.node_states["b"].state == NodeState.DONE
        assert result.node_states["b"].result == "result_b"
