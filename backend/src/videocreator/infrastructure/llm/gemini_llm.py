"""Thin wrapper around google-genai exposing the LLMPort interface.

Kept intentionally minimal — full prompt management lives in the application
layer (PromptRenderer) so the LLM adapter only handles transport.
"""
from __future__ import annotations

import asyncio
from typing import Any

from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderUnavailableError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class GeminiLLM:
    """LLMPort implementation backed by Google Gemini via `google-genai`."""

    name = "gemini"

    def __init__(self, settings: Settings, default_model: str = "gemini-2.0-flash-exp") -> None:
        self._settings = settings
        self._default_model = default_model
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._settings.google_api_key:
            raise ProviderUnavailableError("GOOGLE_API_KEY is not configured")
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderUnavailableError(f"google-genai not installed: {exc}") from exc
        self._client = genai.Client(api_key=self._settings.google_api_key)
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        client = self._ensure_client()
        model_name = model or self._default_model
        config: dict[str, Any] = {"temperature": temperature, "max_output_tokens": 8192}
        if response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = response_schema

        def _call() -> str:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text or ""
            except Exception as exc:
                raise ProviderError(f"gemini call failed: {exc}") from exc

        return await asyncio.to_thread(_call)


__all__ = ["GeminiLLM"]
