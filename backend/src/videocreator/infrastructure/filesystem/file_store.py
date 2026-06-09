"""Safe read/write access to the raw JSON files of a pod.

This is a faithful port of the on-disk pod format: each pod keeps editable
JSON (`config.json`, `prompts.json`, …) plus a shared root `video_rules.json`.
The UI exposes these as raw, editable JSON. All access is confined to the
pods root and limited to a filename whitelist, and writes must parse as
JSON so a typo can't corrupt the file.
"""
from __future__ import annotations

import json
from pathlib import Path

from videocreator.shared.errors import NotFoundError, ValidationError

# Per-pod editable files (under <pods_dir>/<pod>/).
POD_FILES: tuple[str, ...] = (
    "config.json",
    "prompts.json",
    "topics.json",
    "scene_context.json",
    "universe_memory.json",
)
# Shared files at the pods root.
ROOT_FILES: tuple[str, ...] = ("video_rules.json",)


class PodFileStore:
    """Whitelisted JSON file access rooted at the pods directory."""

    def __init__(self, pods_root: Path) -> None:
        self._root = pods_root

    # ---- pod-scoped -------------------------------------------------------
    def list_pod_files(self, pod_name: str) -> list[str]:
        pod_dir = self._pod_dir(pod_name)
        return [name for name in POD_FILES if (pod_dir / name).is_file()]

    def read_pod_file(self, pod_name: str, name: str) -> str:
        return self._read(self._pod_file(pod_name, name))

    def write_pod_file(self, pod_name: str, name: str, content: str) -> None:
        self._write(self._pod_file(pod_name, name), content)

    # ---- root-scoped ------------------------------------------------------
    def list_root_files(self) -> list[str]:
        return [name for name in ROOT_FILES if (self._root / name).is_file()]

    def read_root_file(self, name: str) -> str:
        return self._read(self._root_file(name))

    def write_root_file(self, name: str, content: str) -> None:
        self._write(self._root_file(name), content)

    # ---- internals --------------------------------------------------------
    def _pod_dir(self, pod_name: str) -> Path:
        if not pod_name or "/" in pod_name or "\\" in pod_name or pod_name.startswith("."):
            raise ValidationError(f"invalid pod name: {pod_name!r}")
        return self._root / pod_name

    def _pod_file(self, pod_name: str, name: str) -> Path:
        if name not in POD_FILES:
            raise ValidationError(f"file not editable: {name!r}")
        return self._pod_dir(pod_name) / name

    def _root_file(self, name: str) -> Path:
        if name not in ROOT_FILES:
            raise ValidationError(f"file not editable: {name!r}")
        return self._root / name

    @staticmethod
    def _read(path: Path) -> str:
        if not path.is_file():
            raise NotFoundError(f"file not found: {path.name}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _write(path: Path, content: str) -> None:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"content is not valid JSON: {exc}") from exc
        if not path.parent.is_dir():
            raise NotFoundError(f"target directory does not exist: {path.parent.name}")
        path.write_text(content, encoding="utf-8")


__all__ = ["POD_FILES", "ROOT_FILES", "PodFileStore"]
