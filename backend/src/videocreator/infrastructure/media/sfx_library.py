"""SFX library — resolve a vibe tag to a local sound-effect file.

Catalog lives in ``backend/assets/sfx/catalog.json`` (vibe → list of WAV
filenames). The library validates that referenced files exist at init time
and picks randomly among candidates for variety.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

SfxVibe = Literal[
    "impact",
    "whoosh",
    "rimshot",
    "sad_trombone",
    "bass_drop",
    "transition",
    "reveal",
    "click",
    "none",
]

ALL_VIBES: tuple[str, ...] = (
    "impact", "whoosh", "rimshot", "sad_trombone", "bass_drop",
    "transition", "reveal", "click", "none",
)

_DEFAULT_CATALOG = Path(__file__).resolve().parents[3] / "assets" / "sfx" / "catalog.json"


class SfxLibrary:
    """Resolve SFX vibes to local WAV paths."""

    def __init__(self, catalog_path: Path | None = None) -> None:
        path = catalog_path or _DEFAULT_CATALOG
        if not path.exists():
            log.warning("sfx.catalog.missing", path=str(path))
            self._catalog: dict[str, list[Path]] = {}
            return

        raw: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
        sfx_dir = path.parent
        self._catalog = {}
        for vibe, filenames in raw.items():
            if vibe.startswith("_") or vibe == "none":
                continue
            resolved = []
            for fn in filenames:
                fp = sfx_dir / fn
                if fp.exists():
                    resolved.append(fp)
                else:
                    log.warning("sfx.file.missing", vibe=vibe, file=fn)
            if resolved:
                self._catalog[vibe] = resolved

        log.info("sfx.catalog.loaded", vibes=len(self._catalog),
                 total_files=sum(len(v) for v in self._catalog.values()))

    def resolve(self, vibe: str) -> Path | None:
        """Pick a random SFX file for the given vibe, or None if unavailable."""
        if vibe == "none" or vibe not in self._catalog:
            return None
        candidates = self._catalog[vibe]
        return random.choice(candidates) if candidates else None

    @property
    def available_vibes(self) -> list[str]:
        return list(self._catalog.keys())

    @property
    def is_empty(self) -> bool:
        return not self._catalog


__all__ = ["SfxLibrary", "SfxVibe", "ALL_VIBES"]
