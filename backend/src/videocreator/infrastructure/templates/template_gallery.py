"""Loader for the template gallery — `backend/assets/templates/*.json`.

Each file: metadata + a parametrized DagSpec. Files whose DAG fails validation
are skipped with a warning so one bad template never breaks the gallery.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from videocreator.domain.value_objects import DagSpec
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "assets" / "templates"


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    preview: str | None
    dag: DagSpec


class TemplateGallery:
    """Loads templates once per instance; `reload()` re-reads from disk."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or DEFAULT_TEMPLATES_DIR
        self._templates: dict[str, Template] = {}
        self.reload()

    def reload(self) -> int:
        self._templates.clear()
        if not self._dir.exists():
            log.info("templates.dir_missing", dir=str(self._dir))
            return 0
        for path in sorted(self._dir.glob("*.json")):
            template = _load_one(path)
            if template is not None:
                self._templates[template.id] = template
        log.info("templates.loaded", count=len(self._templates))
        return len(self._templates)

    def list(self) -> list[Template]:
        return list(self._templates.values())

    def get(self, template_id: str) -> Template | None:
        return self._templates.get(template_id)


def _load_one(path: Path) -> Template | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        dag = DagSpec.model_validate(data["dag"])
        return Template(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            description=str(data.get("description", "")),
            tags=tuple(str(t) for t in data.get("tags", [])),
            preview=data.get("preview"),
            dag=dag,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as e:
        log.warning("templates.load_failed", path=str(path), error=str(e))
        return None


__all__ = ["DEFAULT_TEMPLATES_DIR", "Template", "TemplateGallery"]
