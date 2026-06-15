"""Tests for the Higgsfield account balance reader (`hf account status --json`).

The subprocess seam is the `runner` param of `account_balance` — a fake
async `(args) -> (stdout, stderr, code)` callable, mirroring how
`test_higgsfield_adapter.py` replaces `_run`. No real `hf` CLI is invoked.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from videocreator.infrastructure.providers.higgsfield_cli import account_balance


def _settings(cli: str = "hf") -> SimpleNamespace:
    return SimpleNamespace(higgsfield_cli_path=cli)


def _runner(stdout: str = "", stderr: str = "", code: int = 0):
    async def _run(args):
        _run.captured_args = args  # type: ignore[attr-defined]
        return stdout, stderr, code

    return _run


async def test_parses_credits_and_plan_from_good_json() -> None:
    payload = {"credits": 1009.88, "subscription_plan_type": "plus", "email": "toprulo74@gmail.com"}
    run = _runner(stdout=json.dumps(payload))

    result = await account_balance(_settings(), runner=run)

    assert result["available"] is True
    assert result["credits"] == 1009.88
    assert result["plan"] == "plus"
    assert run.captured_args[0] == "hf"  # type: ignore[attr-defined]
    assert run.captured_args[1:4] == ["account", "status", "--json"]  # type: ignore[attr-defined]


async def test_fails_soft_on_nonzero_exit() -> None:
    run = _runner(stdout="", stderr="Session expired", code=1)

    result = await account_balance(_settings(), runner=run)

    assert result == {
        "available": False,
        "credits": None,
        "plan": None,
        "detail": "Session expired",
    }


async def test_fails_soft_on_missing_binary() -> None:
    async def _run(args):
        raise FileNotFoundError(args[0])

    result = await account_balance(_settings("definitely-not-a-real-binary-xyz"), runner=_run)

    assert result["available"] is False
    assert result["credits"] is None
    assert result["plan"] is None
    assert "not found" in result["detail"]


async def test_fails_soft_on_unparseable_output() -> None:
    run = _runner(stdout="not json at all", code=0)

    result = await account_balance(_settings(), runner=run)

    assert result["available"] is False
    assert result["credits"] is None
    assert result["plan"] is None
    assert "not JSON" in result["detail"]


async def test_tolerates_progress_lines_before_json() -> None:
    payload = {"credits": 42.5, "plan_type": "plus"}
    out = "checking session...\nfetching balance...\n" + json.dumps(payload)
    run = _runner(stdout=out)

    result = await account_balance(_settings(), runner=run)

    assert result["available"] is True
    assert result["credits"] == 42.5
    assert result["plan"] == "plus"
