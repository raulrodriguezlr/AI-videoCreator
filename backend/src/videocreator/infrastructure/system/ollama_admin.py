"""Administration helpers for a local Ollama server.

Lets the UI drive Ollama without a terminal: check whether it's up and which
models are installed, start `ollama serve` if it's down, and pull a model with
streamed progress. Pull/status use Ollama's HTTP API (no shell), so a
client-supplied model name can never become a shell-injection vector; `serve`
spawns a fixed argv with no user input.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from collections.abc import AsyncIterator

import httpx

from videocreator.infrastructure.system.runtime_config import JsonRuntimeConfig
from videocreator.shared.config import Settings
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# Conservative model-ref charset, e.g. "qwen2.5:14b-instruct", "llama3.1:8b".
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,128}$")


def is_valid_model_name(model: str) -> bool:
    return bool(_MODEL_RE.match(model))


class OllamaAdmin:
    """Status / serve / pull operations against the configured Ollama server."""

    def __init__(self, settings: Settings, runtime_config: JsonRuntimeConfig) -> None:
        self._settings = settings
        self._rc = runtime_config

    def base_url(self) -> str:
        override = self._rc.get().get("ollama_base_url")
        return str(override or self._settings.ollama_base_url).rstrip("/")

    async def status(self) -> dict[str, object]:
        """Return {running, models, error}. Never raises for a down server."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url()}/api/tags")
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return {"running": True, "models": sorted(filter(None, models)), "error": None}
        except httpx.HTTPError as exc:
            return {"running": False, "models": [], "error": str(exc)}

    async def serve(self) -> dict[str, object]:
        """Start `ollama serve` detached if it isn't already reachable."""
        current = await self.status()
        if current["running"]:
            return current
        try:
            _spawn_detached(["ollama", "serve"])
        except FileNotFoundError:
            return {
                "running": False, "models": [],
                "error": "ollama is not installed or not on PATH",
            }
        # Poll briefly for the server to come up.
        for _ in range(20):
            await asyncio.sleep(0.5)
            current = await self.status()
            if current["running"]:
                return current
        return current

    async def pull(self, model: str) -> AsyncIterator[str]:
        """Yield Ollama's NDJSON pull-progress lines as they arrive."""
        if not is_valid_model_name(model):
            raise ValueError(f"invalid model name: {model!r}")
        async with httpx.AsyncClient(timeout=None) as client, client.stream(
            "POST", f"{self.base_url()}/api/pull", json={"model": model, "stream": True},
        ) as resp:
            if resp.status_code >= httpx.codes.BAD_REQUEST:
                body = (await resp.aread()).decode("utf-8", "replace")[:200]
                raise ValueError(f"ollama pull failed ({resp.status_code}): {body}")
            async for line in resp.aiter_lines():
                if line.strip():
                    yield line


def _spawn_detached(argv: list[str]) -> None:
    """Launch a fully-detached background process, cross-platform."""
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            argv, creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            argv, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )


__all__ = ["OllamaAdmin", "is_valid_model_name"]
