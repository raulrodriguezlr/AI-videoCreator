"""Loader for the shorts rule-book (`shorts_rules.json`).

Keeps the platform policy (max durations, frame sizes) as data next to the
code that consumes it. The loader is the only place that touches the filesystem
so `ShortsRules`/`ShortPlanner` stay pure and unit-testable.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from videocreator.domain.value_objects import ShortsRules

_RULES_FILE = Path(__file__).resolve().parent / "shorts_rules.json"


def load_shorts_rules(path: Path | None = None) -> ShortsRules:
    """Parse and validate the shorts rule-book from `path` (defaults to bundled).

    Validation is delegated to Pydantic via `ShortsRules`, so a malformed file
    fails fast with a clear error rather than silently degrading later.
    """
    rules_path = path or _RULES_FILE
    raw = json.loads(rules_path.read_text(encoding="utf-8"))
    return ShortsRules.model_validate(raw)


@lru_cache(maxsize=1)
def default_shorts_rules() -> ShortsRules:
    """Return the process-wide bundled rule-book (cached)."""
    return load_shorts_rules()


__all__ = ["default_shorts_rules", "load_shorts_rules"]
