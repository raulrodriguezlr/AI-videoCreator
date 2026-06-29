"""Mutable, file-backed runtime overrides.

Some settings (which LLM provider/model to use) must change while the app is
running — without editing `.env` and restarting. This tiny store persists those
overrides to `var/runtime.json`; `Settings` stays the immutable baseline and
the runtime layer wins when present.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# Only these keys may be overridden at runtime — an allow-list keeps the file
# from drifting into a second, untracked config surface.
_ALLOWED = frozenset({
    "llm_provider", "gemini_model", "ollama_model", "ollama_base_url",
    "channels_feature_enabled",
})


class JsonRuntimeConfig:
    """`RuntimeConfigPort` implementation backed by a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            return {k: v for k, v in data.items() if k in _ALLOWED}
        except (json.JSONDecodeError, OSError):
            log.warning("runtime_config.read_failed", path=str(self._path))
            return {}

    def set(self, **overrides: Any) -> dict[str, Any]:
        data = self.get()
        for key, value in overrides.items():
            if key not in _ALLOWED or value is None:
                continue
            data[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("runtime_config.updated", keys=sorted(overrides))
        return data


__all__ = ["JsonRuntimeConfig"]
