"""
config_loader.py — Shared JSON config loader for all modules.

Eliminates duplicate _load_config() methods across VeoProvider,
ScriptGenerator, and TopicEngine.
"""

import json
from typing import Dict, Any


def load_json(path: str) -> Dict[str, Any]:
    """Load and parse a JSON file. Raises FileNotFoundError if missing."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
