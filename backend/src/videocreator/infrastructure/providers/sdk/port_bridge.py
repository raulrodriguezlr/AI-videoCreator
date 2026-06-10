"""Bridge: legacy `VideoProviderPort` adapters → provider-SDK `AdapterBase`.

§15 Fase A migration ("prueba de fuego"): the existing Veo/LTX/Artlist/
ElevenLabs adapters keep their battle-tested code; each providers.d/ entry is
a thin manifest + a subclass of `VideoPortBridge` that builds the legacy port.
New providers should target `AdapterBase` directly — this bridge exists so
migration never rewrites working transport code.
"""
from __future__ import annotations

from typing import Any

from videocreator.domain.ports import VideoProviderPort
from videocreator.domain.value_objects import ScenePrompt
from videocreator.infrastructure.providers.base import CLIP_BUCKET
from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class VideoPortBridge(AdapterBase):
    """Adapts a legacy `VideoProviderPort` to the SDK contract.

    Subclasses implement `_build_port()`; the port and the storage handle are
    resolved lazily from the process container so manifest loading stays
    side-effect free.
    """

    def _build_port(self) -> VideoProviderPort:  # pragma: no cover - abstract
        raise NotImplementedError

    def _container(self) -> Any:
        from videocreator.infrastructure.container import get_container
        return get_container()

    def _port(self) -> VideoProviderPort:
        if not hasattr(self, "_cached_port"):
            self._cached_port = self._build_port()
        return self._cached_port

    async def generate(self, request: GenRequest) -> GenResult:
        prompt = ScenePrompt(
            visual_prompt=request.prompt,
            duration_s=request.duration_s,
            negative_prompt=request.negative_prompt,
        )
        clip = await self._port().generate_clip(prompt, refs=[], seed=request.seed)
        data = await self._container().storage().get(CLIP_BUCKET, clip.storage_key)
        return GenResult(
            video_bytes=data,
            duration_s=clip.duration_s,
            width=clip.width,
            height=clip.height,
            model_id=clip.provider_model or self.manifest.id,
            seed=clip.seed,
            has_audio=clip.has_audio,
            metadata={"storage_key": clip.storage_key},
        )

    async def health(self) -> bool:
        try:
            status = await self._port().availability()
            return bool(status.available)
        except Exception as e:
            log.warning("port_bridge.health_failed",
                        provider=self.manifest.id, error=str(e))
            return False


__all__ = ["VideoPortBridge"]
