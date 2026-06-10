"""ElevenLabs Studio — SDK shim over the legacy provider (§15 Fase A)."""
from __future__ import annotations

from videocreator.domain.ports import VideoProviderPort
from videocreator.infrastructure.providers.sdk.port_bridge import VideoPortBridge


class Adapter(VideoPortBridge):
    def _build_port(self) -> VideoProviderPort:
        return self._container().video_provider("elevenlabs_studio")
