"""Image generation via Google's image models (google-genai).

Implements `ImageGenerationPort`. Used to synthesize character reference
images from a text prompt. Two model families are supported transparently:

* ``gemini-*-image-generation`` → the ``generate_content`` path with an IMAGE
  response modality. Works on standard (free-tier) Gemini API keys.
* ``imagen-*``                  → the Imagen ``generate_images`` predict path,
  which typically needs a paid / Vertex-enabled key.

The model is chosen by ``Settings.image_model``; if a request fails the error
surfaces cleanly in the UI rather than crashing the worker.
"""
from __future__ import annotations

import asyncio
from typing import Any

from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderUnavailableError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class GeminiImageProvider:
    """`ImageGenerationPort` backed by Gemini / Imagen via the google-genai SDK."""

    name = "gemini-image"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
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

    async def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_images: int = 1,
        seed: int | None = None,
    ) -> list[bytes]:
        client = self._ensure_client()
        model = self._settings.image_model
        call = self._imagen_call if model.startswith("imagen") else self._gemini_call
        return await asyncio.to_thread(call, client, model, prompt, max(1, num_images))

    # ---- generate_content path (Gemini flash image models) ----------------
    @staticmethod
    def _gemini_call(client: Any, model: str, prompt: str, _n: int) -> list[bytes]:
        try:
            from google.genai import types
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
        except Exception as exc:
            raise ProviderError(f"image generation failed: {exc}") from exc
        images: list[bytes] = []
        for candidate in getattr(resp, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                blob = getattr(getattr(part, "inline_data", None), "data", None)
                if blob:
                    images.append(bytes(blob))
        if not images:
            raise ProviderError("image model returned no image data")
        return images

    # ---- Imagen predict path ----------------------------------------------
    @staticmethod
    def _imagen_call(client: Any, model: str, prompt: str, n: int) -> list[bytes]:
        try:
            from google.genai import types
            resp = client.models.generate_images(
                model=model, prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=n),
            )
        except Exception as exc:
            raise ProviderError(f"imagen generation failed: {exc}") from exc
        images: list[bytes] = []
        for gen in getattr(resp, "generated_images", None) or []:
            blob = getattr(getattr(gen, "image", None), "image_bytes", None)
            if blob:
                images.append(bytes(blob))
        if not images:
            raise ProviderError("imagen returned no images")
        return images


__all__ = ["GeminiImageProvider"]
