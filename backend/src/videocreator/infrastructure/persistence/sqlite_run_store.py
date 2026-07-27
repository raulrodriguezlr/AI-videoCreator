"""SQLite-backed DAG run store — local-first persistence for resumability.

Persists `DagRun` snapshots (spec + per-node state) so an interrupted run can
be reloaded and resumed by `DagExecutor` without re-running completed nodes.
SQLite stdlib only — no SQLAlchemy, no external broker.

Artifact payloads (`NodeResult.result`) are NOT stored here — they live in
the storage layer (filesystem/object store) and are referenced by the node's
own output paths. On load, `result` is always `None`; a `DONE` node with
`result=None` is treated as already-completed by `DagExecutor` (it only
checks `state`), so resumption still skips it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from videocreator.domain.value_objects import DagSpec
from videocreator.infrastructure.queue.dag_executor import DagRun, NodeResult, NodeState
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS dag_runs (
    run_id TEXT PRIMARY KEY,
    spec_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dag_run_nodes (
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    retries_left INTEGER NOT NULL,
    PRIMARY KEY (run_id, node_id)
)
"""


class SqliteRunStore:
    """Persists `DagRun` snapshots for crash recovery and resumability."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def save(self, run: DagRun) -> None:
        """Upsert the run spec and all node states."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO dag_runs (run_id, spec_json) VALUES (?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET spec_json=excluded.spec_json""",
                (run.run_id, run.spec.model_dump_json()),
            )
            for node_id, ns in run.node_states.items():
                conn.execute(
                    """INSERT INTO dag_run_nodes
                       (run_id, node_id, state, error, retries_left)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(run_id, node_id) DO UPDATE SET
                         state=excluded.state,
                         error=excluded.error,
                         retries_left=excluded.retries_left""",
                    (run.run_id, node_id, ns.state.value, ns.error, ns.retries_left),
                )
        log.info("run_store.saved", run_id=run.run_id, nodes=len(run.node_states))

    def load(self, run_id: str) -> DagRun | None:
        """Rebuild a `DagRun` from its stored spec and node states.

        Returns `None` if `run_id` is unknown. `NodeResult.result` is always
        `None` on load — see module docstring.
        """
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT spec_json FROM dag_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run_row is None:
                return None
            node_rows = conn.execute(
                "SELECT * FROM dag_run_nodes WHERE run_id = ?", (run_id,)
            ).fetchall()

        spec = DagSpec.model_validate_json(run_row["spec_json"])
        run = DagRun(run_id=run_id, spec=spec)
        for row in node_rows:
            run.node_states[row["node_id"]] = NodeResult(
                state=NodeState(row["state"]),
                result=None,
                error=row["error"],
                retries_left=row["retries_left"],
            )
        return run

    def list_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT run_id FROM dag_runs ORDER BY run_id").fetchall()
        return [r["run_id"] for r in rows]

    def delete(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM dag_run_nodes WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM dag_runs WHERE run_id = ?", (run_id,))
        log.info("run_store.deleted", run_id=run_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


__all__ = ["SqliteRunStore"]
