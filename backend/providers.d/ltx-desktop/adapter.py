"""LTX-Desktop — SDK shim over the legacy `LtxDesktopProvider` (§15 Fase A)."""
from __future__ import annotations

from videocreator.domain.ports import VideoProviderPort
from videocreator.infrastructure.providers.sdk.port_bridge import VideoPortBridge


class Adapter(VideoPortBridge):
    def _build_port(self) -> VideoProviderPort:
        from videocreator.infrastructure.providers.ltx_desktop import (
            LtxDesktopProvider,
        )
        container = self._container()
        return LtxDesktopProvider(container.settings, container.storage())
