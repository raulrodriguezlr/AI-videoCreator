"""Tests for trending audio — parsing, legal filter, cache. No Playwright."""
from __future__ import annotations

import time
from pathlib import Path

from videocreator.infrastructure.trends.tiktok_creative_center import (
    TrendCache,
    TrendingSound,
    filter_legal,
    parse_radar_payload,
)


def _sound(id: str = "1", commercial: bool = False, rank: int = 1) -> TrendingSound:
    return TrendingSound(id=id, title=f"song {id}", author="a", rank=rank,
                         is_commercial=commercial)


class TestLegalFilter:
    def test_business_keeps_only_commercial(self) -> None:
        sounds = [_sound("1", commercial=True), _sound("2", commercial=False)]
        result = filter_legal(sounds, is_business=True)
        assert [s.id for s in result] == ["1"]

    def test_personal_keeps_all(self) -> None:
        sounds = [_sound("1", commercial=True), _sound("2", commercial=False)]
        assert len(filter_legal(sounds, is_business=False)) == 2

    def test_missing_metadata_discarded_for_business(self) -> None:
        # is_commercial defaults to False → discard by default
        result = filter_legal([_sound("x")], is_business=True)
        assert result == []


class TestParsePayload:
    def test_parses_sound_list(self) -> None:
        payload = {"data": {"sound_list": [
            {"clip_id": "abc", "title": "Hit", "author": "DJ", "rank": 1,
             "is_commercial": True, "duration": 15.0, "link": "https://x"},
            {"id": "def", "title": "Other", "author": "B", "rank": 2},
        ]}}
        sounds = parse_radar_payload(payload)
        assert len(sounds) == 2
        assert sounds[0].id == "abc"
        assert sounds[0].is_commercial is True
        assert sounds[0].duration_s == 15.0
        assert sounds[1].is_commercial is False

    def test_empty_payload(self) -> None:
        assert parse_radar_payload({}) == []
        assert parse_radar_payload({"data": {}}) == []

    def test_malformed_item_skipped(self) -> None:
        payload = {"data": {"sound_list": [
            {"clip_id": "ok", "title": "Good", "author": "A", "rank": 1},
            {"clip_id": "bad", "title": "Bad", "author": "B", "rank": "not-a-number"},
        ]}}
        sounds = parse_radar_payload(payload)
        assert [s.id for s in sounds] == ["ok"]


class TestTrendCache:
    def test_set_and_get(self, tmp_path: Path) -> None:
        cache = TrendCache(tmp_path / "cache.json")
        cache.set("sounds:ES", [{"id": "1"}])
        assert cache.get("sounds:ES") == [{"id": "1"}]

    def test_miss_on_unknown_key(self, tmp_path: Path) -> None:
        cache = TrendCache(tmp_path / "cache.json")
        assert cache.get("nope") is None

    def test_expired_entry_misses(self, tmp_path: Path, monkeypatch) -> None:
        cache = TrendCache(tmp_path / "cache.json")
        cache.set("k", [{"id": "1"}])
        future = time.time() + 25 * 3600
        monkeypatch.setattr(time, "time", lambda: future)
        assert cache.get("k") is None

    def test_corrupt_cache_file(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text("not json{{{")
        cache = TrendCache(p)
        assert cache.get("k") is None
        cache.set("k", [])  # must not raise
