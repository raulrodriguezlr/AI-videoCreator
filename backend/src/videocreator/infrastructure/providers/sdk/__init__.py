"""Provider SDK — declarative manifest-driven provider plugins."""
from videocreator.infrastructure.providers.sdk.adapter_base import AdapterBase
from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest
from videocreator.infrastructure.providers.sdk.registry import LoadedProvider, ProviderRegistry

__all__ = ["AdapterBase", "LoadedProvider", "ProviderManifest", "ProviderRegistry"]
