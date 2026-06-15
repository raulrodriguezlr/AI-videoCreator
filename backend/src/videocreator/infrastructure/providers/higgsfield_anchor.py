"""Higgsfield character-anchor client — bind a local character to a reusable
Higgsfield **Soul** identity via the official `hf` CLI.

A Soul is a trained, face-faithful identity (3-20 reference images, ~10 min
training) reusable across image/video generations with `--soul-id <id>`. We
drive it through the CLI so it uses the user's PLUS subscription credits (same
reasoning as the generation adapter — see providers.d/higgsfield/adapter.py).

────────────────────────────────────────────────────────────────────────────
CONTRACT BLOCK — verified against @higgsfield/cli v0.2.x:
  • Train:  hf soul-id create --name <name> --soul-2 --image <path> [--image ...] --json
            → JSON containing the new soul id (dug tolerantly below).
  • Status: hf soul-id wait <soul_id>     (blocks; NOT used here — too slow for HTTP).
  • Reuse:  hf generate create <model> --prompt "..." --soul-id <soul_id>
Training is async (~10 min); we submit and store the id immediately, leaving the
character "training" until the Soul is ready. Needs >= `_MIN_IMAGES` references.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.shared.config import Settings
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: Higgsfield Soul training needs at least this many reference images.
_MIN_IMAGES = 3
#: Where the new soul id can appear in the CLI's JSON output.
_ID_KEYS = ("soul_id", "id", "soul", "soulId")


@dataclass(frozen=True)
class AnchorResult:
    """Outcome of an anchor sync — `ref_id` is None when nothing was created."""

    ref_id: str | None
    kind: str | None  # "soul"
    synced: bool
    detail: str


def _dig_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for k in _ID_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v:
                return v
        for k in ("results", "items", "data"):
            inner = data.get(k)
            if isinstance(inner, list) and inner:
                got = _dig_id(inner[0])
                if got:
                    return got
    return None


class HiggsfieldAnchorClient:
    """Train/lookup reusable Higgsfield Soul identities for local characters."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def available(self) -> bool:
        return bool(self._settings.higgsfield_cli_path)

    async def create_soul(self, *, name: str, image_paths: list[Path]) -> AnchorResult:
        """Train a Soul from local reference images. Fails soft (never raises)."""
        if len(image_paths) < _MIN_IMAGES:
            return AnchorResult(
                None, None, False,
                f"se necesitan al menos {_MIN_IMAGES} imágenes de referencia para "
                f"entrenar un Soul (hay {len(image_paths)})",
            )
        args = [self._settings.higgsfield_cli_path or "hf",
                "soul-id", "create", "--name", name, "--soul-2", "--json"]
        for p in image_paths:
            args += ["--image", str(p)]

        out, err, code = await self._run(args)
        if code != 0:
            return AnchorResult(
                None, None, False,
                f"el CLI de Higgsfield falló al crear el Soul: {(err or out)[:200]}",
            )
        try:
            data = json.loads(out.strip()) if out.strip() else {}
        except json.JSONDecodeError:
            data = {}
        soul_id = _dig_id(data)
        if not soul_id:
            return AnchorResult(None, None, False,
                                f"no se obtuvo soul_id del CLI: {out[:200]}")
        log.info("higgsfield.anchor.soul_created", name=name, soul_id=soul_id)
        return AnchorResult(
            soul_id, "soul", True,
            "Soul en entrenamiento (~10 min). Reutilizable en la generación "
            "cuando esté listo.",
        )

    async def _run(self, args: list[str]) -> tuple[str, str, int]:
        """Run the hf CLI; returns (stdout, stderr, returncode). Isolated for tests."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return "", f"CLI not found at '{args[0]}'", 127
        out, err = await proc.communicate()
        return (out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                proc.returncode or 0)


__all__ = ["AnchorResult", "HiggsfieldAnchorClient"]
