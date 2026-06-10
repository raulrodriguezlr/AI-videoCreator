"""Unit tests for SfxLibrary."""
import json
from pathlib import Path

import pytest

from videocreator.infrastructure.media.sfx_library import SfxLibrary


@pytest.fixture()
def sfx_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sfx"
    d.mkdir()
    (d / "impact_01.wav").write_bytes(b"RIFF")
    (d / "impact_02.wav").write_bytes(b"RIFF")
    (d / "whoosh_01.wav").write_bytes(b"RIFF")
    catalog = {
        "impact": ["impact_01.wav", "impact_02.wav"],
        "whoosh": ["whoosh_01.wav"],
        "rimshot": ["missing.wav"],
        "none": [],
    }
    (d / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return d


def test_loads_existing_files(sfx_dir: Path) -> None:
    lib = SfxLibrary(sfx_dir / "catalog.json")
    assert "impact" in lib.available_vibes
    assert "whoosh" in lib.available_vibes
    assert "rimshot" not in lib.available_vibes  # file missing


def test_resolve_returns_path(sfx_dir: Path) -> None:
    lib = SfxLibrary(sfx_dir / "catalog.json")
    p = lib.resolve("impact")
    assert p is not None
    assert p.name.startswith("impact_")


def test_resolve_none_vibe(sfx_dir: Path) -> None:
    lib = SfxLibrary(sfx_dir / "catalog.json")
    assert lib.resolve("none") is None


def test_resolve_unknown_vibe(sfx_dir: Path) -> None:
    lib = SfxLibrary(sfx_dir / "catalog.json")
    assert lib.resolve("nonexistent") is None


def test_missing_catalog_graceful() -> None:
    lib = SfxLibrary(Path("/does/not/exist/catalog.json"))
    assert lib.is_empty
    assert lib.resolve("impact") is None
