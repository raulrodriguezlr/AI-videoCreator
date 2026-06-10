"""Tests for template gallery — shipped assets + corrupt-file resilience."""
from __future__ import annotations

import json
from pathlib import Path

from videocreator.infrastructure.templates.template_gallery import (
    DEFAULT_TEMPLATES_DIR,
    TemplateGallery,
)


class TestShippedTemplates:
    def test_loads_shipped_gallery(self) -> None:
        gallery = TemplateGallery()
        ids = {t.id for t in gallery.list()}
        assert {"native-short-basic", "multiply-full", "carousel-pack"} <= ids

    def test_shipped_dags_are_valid(self) -> None:
        # Construction already validates; assert nodes are present.
        for t in TemplateGallery().list():
            assert len(t.dag.nodes) >= 1
            assert t.dag.topo_order()

    def test_get_by_id(self) -> None:
        gallery = TemplateGallery()
        t = gallery.get("multiply-full")
        assert t is not None
        assert "master" in {n.id for n in t.dag.nodes}
        assert gallery.get("nope") is None


class TestCustomDir:
    def test_corrupt_and_invalid_files_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "good.json").write_text(json.dumps({
            "id": "good", "name": "Good", "dag": {"nodes": [
                {"id": "n1", "capability": "llm_text"}]},
        }), encoding="utf-8")
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        (tmp_path / "cyclic.json").write_text(json.dumps({
            "id": "cyclic", "dag": {"nodes": [
                {"id": "a", "capability": "x", "depends_on": ["b"]},
                {"id": "b", "capability": "x", "depends_on": ["a"]}]},
        }), encoding="utf-8")
        gallery = TemplateGallery(tmp_path)
        assert [t.id for t in gallery.list()] == ["good"]

    def test_missing_dir_is_empty(self, tmp_path: Path) -> None:
        gallery = TemplateGallery(tmp_path / "nowhere")
        assert gallery.list() == []

    def test_reload_picks_up_new_files(self, tmp_path: Path) -> None:
        gallery = TemplateGallery(tmp_path)
        assert gallery.list() == []
        (tmp_path / "late.json").write_text(json.dumps({
            "id": "late", "dag": {"nodes": [
                {"id": "n", "capability": "x"}]},
        }), encoding="utf-8")
        assert gallery.reload() == 1
        assert gallery.get("late") is not None

    def test_default_dir_exists(self) -> None:
        assert DEFAULT_TEMPLATES_DIR.exists()
