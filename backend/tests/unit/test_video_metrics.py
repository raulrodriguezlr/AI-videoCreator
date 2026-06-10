"""Tests for video_metrics store, CSV fallback, and LinUCB reward extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.infrastructure.metrics.video_metrics import (
    VideoMetric,
    VideoMetricsStore,
    linucb_reward,
    parse_analytics_rows,
    retention_at_3s,
)


def _metric(video_id: str = "v1", date: str = "2026-06-01", **kw) -> VideoMetric:
    return VideoMetric(video_id=video_id, episode_id="ep1", date=date,
                       views=kw.pop("views", 100), **kw)


class TestRetention:
    def test_curve_lookup(self) -> None:
        # 30s video, 11 samples → 3s mark = index 1
        curve = (1.0, 0.8, 0.6, 0.5, 0.4, 0.35, 0.3, 0.28, 0.25, 0.2, 0.1)
        assert retention_at_3s(curve, 30.0) == pytest.approx(0.8)

    def test_short_video_clamps_to_end(self) -> None:
        # 2s video → 3s mark past the end → last sample
        assert retention_at_3s((1.0, 0.5), 2.0) == pytest.approx(0.5)

    def test_empty_curve_zero(self) -> None:
        assert retention_at_3s((), 30.0) == 0.0
        assert retention_at_3s((0.9,), 0.0) == 0.0

    def test_linucb_reward_delegates(self) -> None:
        m = _metric(retention_curve=(1.0, 0.7, 0.4))
        assert linucb_reward(m, 6.0) == pytest.approx(0.7)


class TestStore:
    def test_roundtrip(self, tmp_path: Path) -> None:
        store = VideoMetricsStore(tmp_path / "m.db")
        store.record(_metric(avg_view_pct=0.62, retention_curve=(1.0, 0.5)))
        result = store.list_for_episode("ep1")
        assert len(result) == 1
        assert result[0].views == 100
        assert result[0].retention_curve == (1.0, 0.5)
        assert result[0].avg_view_pct == pytest.approx(0.62)

    def test_upsert_same_day(self, tmp_path: Path) -> None:
        store = VideoMetricsStore(tmp_path / "m.db")
        store.record(_metric(views=10))
        store.record(_metric(views=50))
        result = store.list_for_video("v1")
        assert len(result) == 1
        assert result[0].views == 50

    def test_list_for_video_ordered(self, tmp_path: Path) -> None:
        store = VideoMetricsStore(tmp_path / "m.db")
        store.record(_metric(date="2026-06-02", views=20))
        store.record(_metric(date="2026-06-01", views=10))
        result = store.list_for_video("v1")
        assert [m.views for m in result] == [10, 20]

    def test_import_csv_skips_malformed(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "metrics.csv"
        csv_file.write_text(
            "video_id,date,views,avg_view_pct\n"
            "v1,2026-06-01,120,0.55\n"
            "v2,2026-06-01,not-a-number,\n"
            "v3,2026-06-01,80,\n",
            encoding="utf-8",
        )
        store = VideoMetricsStore(tmp_path / "m.db")
        assert store.import_csv(csv_file, episode_id="ep1") == 2
        assert len(store.list_for_episode("ep1")) == 2


class TestParseAnalyticsRows:
    def test_parses_rows(self) -> None:
        rows = [
            {"video": "abc", "day": "2026-06-01", "views": 500,
             "averageViewPercentage": 48.5, "audienceWatchRatio": [1.0, 0.6, 0.3]},
        ]
        metrics = parse_analytics_rows(rows, episode_id="ep1")
        assert len(metrics) == 1
        assert metrics[0].video_id == "abc"
        assert metrics[0].avg_view_pct == pytest.approx(0.485)
        assert metrics[0].retention_curve == (1.0, 0.6, 0.3)

    def test_malformed_row_skipped(self) -> None:
        rows = [
            {"video": "ok", "day": "2026-06-01", "views": 1},
            {"day": "2026-06-01", "views": 1},  # missing video id
            {"video": "bad", "views": "NaN-ish", "audienceWatchRatio": "x"},
        ]
        metrics = parse_analytics_rows(rows, episode_id="ep1")
        assert [m.video_id for m in metrics] == ["ok"]
