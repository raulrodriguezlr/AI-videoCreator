"""Tests for PodFileStore — whitelist, JSON validation, path safety."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from videocreator.infrastructure.filesystem.file_store import PodFileStore
from videocreator.shared.errors import NotFoundError, ValidationError


def _store(tmp_path: Path) -> tuple[PodFileStore, Path]:
    root = tmp_path / "pods"
    (root / "kids_story").mkdir(parents=True)
    (root / "kids_story" / "config.json").write_text('{"series_name": "Tico"}', encoding="utf-8")
    (root / "video_rules.json").write_text('{"max": 3}', encoding="utf-8")
    return PodFileStore(root), root


def test_lists_only_existing_whitelisted_pod_files(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    assert store.list_pod_files("kids_story") == ["config.json"]


def test_read_write_roundtrip(tmp_path: Path) -> None:
    store, root = _store(tmp_path)

    store.write_pod_file("kids_story", "config.json", '{"series_name": "Edited"}')

    assert json.loads(store.read_pod_file("kids_story", "config.json"))["series_name"] == "Edited"
    on_disk = (root / "kids_story" / "config.json").read_text(encoding="utf-8")
    assert "Edited" in on_disk


def test_write_rejects_invalid_json(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    with pytest.raises(ValidationError, match="not valid JSON"):
        store.write_pod_file("kids_story", "config.json", "{not json")


def test_rejects_non_whitelisted_filename(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    with pytest.raises(ValidationError, match="not editable"):
        store.read_pod_file("kids_story", "secrets.json")


def test_rejects_path_traversal_pod_name(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    with pytest.raises(ValidationError, match="invalid pod name"):
        store.read_pod_file("../../etc", "config.json")


def test_root_file_roundtrip(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    assert store.list_root_files() == ["video_rules.json"]

    store.write_root_file("video_rules.json", '{"max": 5}')

    assert json.loads(store.read_root_file("video_rules.json"))["max"] == 5


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    with pytest.raises(NotFoundError):
        store.read_pod_file("kids_story", "prompts.json")
