"""`ImageGenerationPort` backed by an SDK provider's text_to_image adapter.

Lets the character-reference / image-generation surface use any SDK provider
that declares `text_to_image` (e.g. Higgsfield's Soul, Seedream, Nano-Banana)
instead of only Gemini/Imagen. It is a thin bridge: it reuses the already
verified provider adapter (auth, submit-and-poll, download) and just adapts the
`GenResult.video_bytes` payload to the `list[bytes]` the port returns.

The concrete model is fixed per instance (`model_id`), so the `ImageGenerationPort`
signature stays unchanged — the caller picks the engine+model when the container
builds the provider, not on every `generate()` call.
"""
from __future__ import annotations

from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest
from videocreator.shared.errors import ProviderError, ProviderUnavailableError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class SdkImageProvider:
    """`ImageGenerationPort` over an SDK `text_to_image` provider/model."""

    def __init__(self, registry: object, provider_id: str, model_id: str) -> None:
        self._registry = registry
        self._provider_id = provider_id
        self._model_id = model_id

    @property
    def name(self) -> str:
        return f"{self._provider_id}:{self._model_id}"

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
        loaded = self._registry.get(self._provider_id)  # type: ignore[attr-defined]
        if loaded is None:
            raise ProviderUnavailableError(
                f"SDK provider '{self._provider_id}' is not available "
                "(not discovered, or its credentials are missing)"
            )
        req = GenRequest(
            prompt=prompt,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
            model_id=self._model_id,
        )
        out: list[bytes] = []
        # Most image models render one frame per request; loop for num_images so
        # the contract (return N blobs) holds regardless of the provider.
        for _ in range(max(1, num_images)):
            result = await loaded.adapter.generate(req)
            if not result.video_bytes:
                raise ProviderError(
                    f"{self.name} returned no image data for model '{self._model_id}'"
                )
            out.append(result.video_bytes)
        return out


__all__ = ["SdkImageProvider"]
