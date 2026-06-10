"""SQLite-backed cost ledger — local-first persistence for provider spend.

Drop-in replacement for `domain.services.capability_router.CostLedger`: same
public API (`record`, `total_cost`, `check_budget`, `entries`), backed by a
single `cost_ledger` table so spend survives process restarts. SQLite stdlib
only — no SQLAlchemy, no external services.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from videocreator.domain.services.capability_router import CostEntry
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS cost_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    units REAL NOT NULL,
    unit_type TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    timestamp REAL NOT NULL,
    episode_id TEXT
)
"""


class SqliteCostLedger:
    """SQLite-backed cost tracking with budget enforcement.

    Same surface as the in-memory `CostLedger` so it can be swapped in
    wherever the latter is used.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def record(self, entry: CostEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO cost_ledger
                   (provider_id, capability, units, unit_type, cost_usd, timestamp, episode_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.provider_id,
                    entry.capability,
                    entry.units,
                    entry.unit_type,
                    entry.cost_usd,
                    entry.timestamp,
                    entry.episode_id,
                ),
            )
        log.info(
            "cost_ledger.recorded",
            provider=entry.provider_id,
            capability=entry.capability,
            cost_usd=entry.cost_usd,
            episode_id=entry.episode_id,
        )

    def total_cost(self, *, episode_id: str | None = None) -> float:
        with self._connect() as conn:
            if episode_id is not None:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM cost_ledger "
                    "WHERE episode_id = ?",
                    (episode_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM cost_ledger"
                ).fetchone()
        return float(row["total"])

    def check_budget(self, estimated_cost: float, budget_usd: float | None) -> bool:
        """Returns True if adding estimated_cost stays within budget."""
        if budget_usd is None:
            return True
        return self.total_cost() + estimated_cost <= budget_usd

    @property
    def entries(self) -> list[CostEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cost_ledger ORDER BY id"
            ).fetchall()
        return [self._to_entry(r) for r in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_entry(row: sqlite3.Row) -> CostEntry:
        return CostEntry(
            provider_id=row["provider_id"],
            capability=row["capability"],
            units=row["units"],
            unit_type=row["unit_type"],
            cost_usd=row["cost_usd"],
            timestamp=row["timestamp"],
            episode_id=row["episode_id"],
        )


__all__ = ["SqliteCostLedger"]
