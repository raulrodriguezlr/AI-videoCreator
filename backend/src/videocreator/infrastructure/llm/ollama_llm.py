"""LLMPort implementation backed by a local Ollama server.

Lets the whole text-generation surface (scripts, topics, the pod wizard, SEO,
idea enhancement) run fully offline on consumer GPUs — no cloud key required.
A 12 GB card comfortably runs Qwen2.5-14B-Instruct (Q4), Mistral-Nemo-12B or
Llama-3.1-8B; pick via `OLLAMA_MODEL`.

Transport only: prompt construction stays in the application layer, exactly
like `GeminiLLM`, so swapping providers never touches the prompts.

Structured output: Ollama's `format="json"` guarantees syntactically valid
JSON across every server version. When a `response_schema` is supplied we also
append a compact rendering of it to the prompt so the model targets the right
shape — the application layer then validates/coerces the parsed result.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderUnavailableError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class OllamaLLM:
    """LLMPort implementation talking to Ollama's `/api/generate` endpoint.

    If `ensure_running` is supplied, a failed connection triggers one attempt
    to start the server (e.g. `ollama serve`) before retrying — so the model
    "just works" from the UI without the user opening a terminal.
    """

    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        default_model: str | None = None,
        *,
        ensure_running: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._default_model = default_model or settings.ollama_model
        self._timeout = httpx.Timeout(settings.ollama_timeout_seconds)
        self._ensure_running = ensure_running

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "prompt": self._build_prompt(prompt, response_schema),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if response_schema is not None:
            body["format"] = "json"
        return self._parse(await self._post(body, allow_autostart=True))

    async def _post(self, body: dict[str, Any], *, allow_autostart: bool) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/generate", json=body)
        except httpx.ConnectError as exc:
            if allow_autostart and self._ensure_running is not None:
                log.info("ollama.autostart", base_url=self._base_url)
                await self._ensure_running()
                return await self._post(body, allow_autostart=False)
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self._base_url} — is `ollama serve` running?"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProviderUnavailableError(
                f"ollama model '{body['model']}' not found — run `ollama pull {body['model']}`"
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProviderError(f"ollama returned {response.status_code}: {response.text[:200]}")
        return response

    @staticmethod
    def _parse(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"ollama returned non-JSON envelope: {exc}") from exc
        return str(payload.get("response", ""))

    @staticmethod
    def _build_prompt(prompt: str, response_schema: dict[str, Any] | None) -> str:
        """Append a schema hint when structured output is requested.

        Ollama's constrained `format="json"` only enforces *valid* JSON, not a
        particular shape, so we steer the shape through the prompt.
        """
        if response_schema is None:
            return prompt
        schema_text = json.dumps(response_schema, ensure_ascii=False, indent=2)
        return (
            f"{prompt}\n\n"
            "Respond with a single JSON object (no markdown, no prose) that "
            f"conforms to this JSON Schema:\n{schema_text}"
        )


__all__ = ["OllamaLLM"]
