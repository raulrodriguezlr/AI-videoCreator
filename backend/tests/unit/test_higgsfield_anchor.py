"""Tests for the Higgsfield Soul anchor client (CLI-driven, fail-soft)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from videocreator.infrastructure.providers.higgsfield_anchor import (
    HiggsfieldAnchorClient,
)


def _client(stdout="", code=0, stderr="") -> HiggsfieldAnchorClient:
    c = HiggsfieldAnchorClient(SimpleNamespace(higgsfield_cli_path="hf"))  # type: ignore[arg-type]

    async def _run(args):
        c.last_args = args  # type: ignore[attr-defined]
        return stdout, stderr, code

    c._run = _run  # type: ignore[method-assign]
    return c


_IMGS = [Path("a.png"), Path("b.png"), Path("c.png")]


async def test_create_soul_parses_id_and_builds_args() -> None:
    c = _client(stdout=json.dumps({"soul_id": "soul_abc"}))
    res = await c.create_soul(name="Tico", image_paths=_IMGS)

    assert res.synced is True
    assert res.ref_id == "soul_abc"
    assert res.kind == "soul"
    args = c.last_args  # type: ignore[attr-defined]
    assert args[:4] == ["hf", "soul-id", "create", "--name"]
    assert "--soul-2" in args and "--json" in args
    assert args.count("--image") == 3


async def test_too_few_images_fails_soft() -> None:
    c = _client()
    res = await c.create_soul(name="Tico", image_paths=[Path("only.png")])
    assert res.synced is False
    assert "al menos" in res.detail


async def test_cli_error_fails_soft() -> None:
    c = _client(stdout="", code=1, stderr="Not authenticated")
    res = await c.create_soul(name="Tico", image_paths=_IMGS)
    assert res.synced is False
    assert "Not authenticated" in res.detail


async def test_no_id_in_output_fails_soft() -> None:
    c = _client(stdout=json.dumps({"status": "ok"}))
    res = await c.create_soul(name="Tico", image_paths=_IMGS)
    assert res.synced is False
    assert res.ref_id is None
