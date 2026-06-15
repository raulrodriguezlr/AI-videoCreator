"""Higgsfield account balance — read the Plus subscription credit balance via
the official `hf` CLI.

Why the CLI: the user's PLUS SUBSCRIPTION credits live in the web/OAuth
session wallet (the same one `hf generate ...` spends), not the developer
REST API key's wallet. `hf account status --json` is the first-party way to
read that balance (see `backend/providers.d/higgsfield/adapter.py` for the
full CLI-driving contract notes).

This module is FAIL SOFT by design: callers (the `/system/higgsfield/balance`
endpoint) always get a dict back, never an exception — missing binary, an
unauthenticated session, or unexpected output all map to
`{"available": False, "credits": None, "plan": None, "detail": "<reason>"}`.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from videocreator.shared.config import Settings
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: Keys (in priority order) that may hold the credit balance / plan name in
#: `hf account status --json` output. Tolerant on purpose — the CLI's JSON
#: shape isn't formally documented.
_CREDIT_KEYS: tuple[str, ...] = ("credits", "credit_balance", "balance", "plan_credits")
_PLAN_KEYS: tuple[str, ...] = ("subscription_plan_type", "plan_type", "plan", "subscription_plan")


def _unavailable(detail: str) -> dict[str, Any]:
    return {"available": False, "credits": None, "plan": None, "detail": detail}


def _find_numeric(obj: Any, keys: tuple[str, ...]) -> float | None:
    """Depth-first search for the first numeric value under any of `keys`."""
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return float(val)
        for val in obj.values():
            found = _find_numeric(val, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_numeric(item, keys)
            if found is not None:
                return found
    return None


def _find_string(obj: Any, keys: tuple[str, ...]) -> str | None:
    """Depth-first search for the first non-empty string value under any of `keys`."""
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        for val in obj.values():
            found = _find_string(val, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_string(item, keys)
            if found is not None:
                return found
    return None


async def _run(args: list[str]) -> tuple[str, str, int]:
    """Run the hf CLI, returning (stdout, stderr, returncode).

    Raises FileNotFoundError if the binary cannot be found — callers handle it.
    """
    import subprocess
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=False, # We decode it manually below
        )
        return (
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"),
            proc.returncode
        )
    except FileNotFoundError:
        raise


async def account_balance(settings: Settings, *, runner: Any = None) -> dict[str, Any]:
    """Return the user's Higgsfield Plus subscription credit balance.

    `runner` is an optional async `(args) -> (stdout, stderr, code)` callable,
    injectable for tests; defaults to `_run` (a real subprocess).
    Never raises — see module docstring for the fail-soft contract.
    """
    run = runner or _run
    cli_path = settings.higgsfield_cli_path or "hf"
    args = [cli_path, "account", "status", "--json"]

    try:
        stdout, stderr, code = await run(args)
    except FileNotFoundError:
        return _unavailable(f"higgsfield CLI not found at '{cli_path}'")
    except OSError as exc:
        return _unavailable(f"higgsfield CLI failed to start: {exc}")

    if code != 0:
        reason = stderr.strip() or stdout.strip() or f"exit code {code}"
        log.warning("higgsfield.cli.balance.failed", code=code, reason=reason[:200])
        return _unavailable(reason[:300])

    try:
        data = json.loads(stdout.strip())
    except json.JSONDecodeError:
        # Fall back to the last JSON-parseable line (progress lines may precede it).
        data = None
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if data is None:
            return _unavailable(f"higgsfield CLI output was not JSON: {stdout.strip()[:200]}")

    credits = _find_numeric(data, _CREDIT_KEYS)
    plan = _find_string(data, _PLAN_KEYS)
    if credits is None and plan is None:
        return _unavailable("higgsfield CLI JSON had no recognizable credits/plan fields")

    return {"available": True, "credits": credits, "plan": plan, "detail": "ok"}


__all__ = ["account_balance"]
