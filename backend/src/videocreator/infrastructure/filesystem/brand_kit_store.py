"""Filesystem store for brand kits — one JSON per pod (local-first, §10.3)."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from videocreator.domain.services.brand_kit import BrandKit
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class BrandKitStore:
    """`<base_dir>/<pod_id>/brand_kit.json` per pod."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _path(self, pod_id: str) -> Path:
        return self._base / pod_id / "brand_kit.json"

    def get(self, pod_id: str) -> BrandKit | None:
        path = self._path(pod_id)
        if not path.exists():
            return None
        try:
            return BrandKit.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, json.JSONDecodeError, OSError) as e:
            log.warning("brand_kit.load_failed", pod_id=pod_id, error=str(e))
            return None

    def save(self, kit: BrandKit) -> BrandKit:
        path = self._path(kit.pod_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kit.model_dump_json(indent=2), encoding="utf-8")
        log.info("brand_kit.saved", pod_id=kit.pod_id)
        return kit

    def delete(self, pod_id: str) -> bool:
        path = self._path(pod_id)
        if path.exists():
            path.unlink()
            return True
        return False


__all__ = ["BrandKitStore"]
