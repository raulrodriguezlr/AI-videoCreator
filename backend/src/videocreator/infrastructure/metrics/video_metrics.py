"""video_metrics store + LinUCB reward extraction (§16.14).

Nightly job ingests YouTube Analytics rows; the universal fallback is a manual
CSV import from the UI. SQLite-only on purpose (local-first) — one table:

    video_metrics(video_id, episode_id, date, views, avg_view_pct,
                  retention_curve_json)

The 3-second retention extracted from `audienceWatchRatio` is the reward
signal for the hook bandit (§16.2).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS video_metrics (
    video_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    date TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    avg_view_pct REAL,
    retention_curve_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (video_id, date)
)
"""


@dataclass(frozen=True)
class VideoMetric:
    video_id: str
    episode_id: str
    date: str  # ISO YYYY-MM-DD
    views: int = 0
    avg_view_pct: float | None = None
    retention_curve: tuple[float, ...] = ()


def retention_at_3s(curve: tuple[float, ...], video_duration_s: float) -> float:
    """Audience ratio still watching at the 3-second mark, 0-1.

    `audienceWatchRatio` samples are evenly spaced over the video duration;
    we pick the sample nearest to t=3s. Empty curve or non-positive duration
    yields 0.0 (no reward, never an exception).
    """
    if not curve or video_duration_s <= 0:
        return 0.0
    position = min(1.0, 3.0 / video_duration_s)
    idx = round(position * (len(curve) - 1))
    return max(0.0, min(1.0, curve[idx]))


def linucb_reward(metric: VideoMetric, video_duration_s: float) -> float:
    """Reward for the hook bandit: 3s retention per §16.2/§16.14."""
    return retention_at_3s(metric.retention_curve, video_duration_s)


def parse_analytics_rows(
    rows: list[dict[str, Any]], *, episode_id: str,
) -> list[VideoMetric]:
    """Map YouTube Analytics row dicts to VideoMetric. Malformed rows skipped."""
    metrics: list[VideoMetric] = []
    for row in rows:
        try:
            ratio = row.get("audienceWatchRatio")
            curve: tuple[float, ...]
            if isinstance(ratio, (list, tuple)):
                curve = tuple(float(v) for v in ratio)
            elif ratio is None:
                curve = ()
            else:
                curve = (float(ratio),)
            metrics.append(VideoMetric(
                video_id=str(row["video"]),
                episode_id=episode_id,
                date=str(row.get("day", "")),
                views=int(row.get("views", 0)),
                avg_view_pct=(
                    float(row["averageViewPercentage"]) / 100.0
                    if row.get("averageViewPercentage") is not None else None
                ),
                retention_curve=curve,
            ))
        except (KeyError, TypeError, ValueError) as e:
            log.warning("metrics.parse_row_failed", error=str(e))
    return metrics


class VideoMetricsStore:
    """SQLite-backed store. One row per (video_id, date) — upsert semantics."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def record(self, metric: VideoMetric) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO video_metrics
                   (video_id, episode_id, date, views, avg_view_pct, retention_curve_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(video_id, date) DO UPDATE SET
                     views=excluded.views,
                     avg_view_pct=excluded.avg_view_pct,
                     retention_curve_json=excluded.retention_curve_json""",
                (metric.video_id, metric.episode_id, metric.date, metric.views,
                 metric.avg_view_pct, json.dumps(list(metric.retention_curve))),
            )

    def record_many(self, metrics: list[VideoMetric]) -> int:
        for m in metrics:
            self.record(m)
        return len(metrics)

    def list_for_episode(self, episode_id: str) -> list[VideoMetric]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM video_metrics WHERE episode_id = ? ORDER BY date",
                (episode_id,),
            ).fetchall()
        return [self._to_metric(r) for r in rows]

    def list_for_video(self, video_id: str) -> list[VideoMetric]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM video_metrics WHERE video_id = ? ORDER BY date",
                (video_id,),
            ).fetchall()
        return [self._to_metric(r) for r in rows]

    def import_csv(self, csv_path: Path, *, episode_id: str) -> int:
        """Manual fallback import. Columns: video_id,date,views[,avg_view_pct].
        Malformed rows are skipped with a warning. Returns rows imported."""
        imported = 0
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    avg_raw = (row.get("avg_view_pct") or "").strip()
                    self.record(VideoMetric(
                        video_id=row["video_id"].strip(),
                        episode_id=episode_id,
                        date=row["date"].strip(),
                        views=int(row["views"]),
                        avg_view_pct=float(avg_raw) if avg_raw else None,
                    ))
                    imported += 1
                except (KeyError, TypeError, ValueError) as e:
                    log.warning("metrics.csv_row_skipped", error=str(e))
        log.info("metrics.csv_imported", count=imported, path=str(csv_path))
        return imported

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_metric(row: sqlite3.Row) -> VideoMetric:
        try:
            curve = tuple(float(v) for v in json.loads(row["retention_curve_json"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            curve = ()
        return VideoMetric(
            video_id=row["video_id"],
            episode_id=row["episode_id"],
            date=row["date"],
            views=row["views"],
            avg_view_pct=row["avg_view_pct"],
            retention_curve=curve,
        )


__all__ = [
    "VideoMetric",
    "VideoMetricsStore",
    "linucb_reward",
    "parse_analytics_rows",
    "retention_at_3s",
]
