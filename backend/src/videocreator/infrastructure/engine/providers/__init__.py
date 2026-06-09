"""
Provider Factory — Returns the correct video provider based on variables.py config.

Usage:
    from videocreator.infrastructure.engine.providers import get_provider
    provider = get_provider("pods/kids_story/config.json")
"""

from videocreator.infrastructure.engine import variables
from videocreator.infrastructure.engine.providers.veo_provider import VeoProvider
from videocreator.infrastructure.engine.providers.ltx_desktop_provider import LtxDesktopProvider
from videocreator.infrastructure.engine.providers.http_cloud_providers import (
    ArtlistProvider,
    ElevenLabsStudioProvider,
)


def get_provider(pod_config_path: str):
    """
    Factory returning the video provider for the *current* VIDEO_PROVIDER.

    Reads ``variables.VIDEO_PROVIDER`` live (the handler mutates it per render);
    a plain ``from variables import VIDEO_PROVIDER`` would capture the import-time
    value and always build Veo.

    Args:
        pod_config_path: Path to the pod's config.json file.

    Returns:
        An instance of BaseVideoProvider (VeoProvider or LtxDesktopProvider).

    Raises:
        ValueError: If VIDEO_PROVIDER is not recognized.
    """
    provider = variables.VIDEO_PROVIDER
    if provider == "veo":
        return VeoProvider(pod_config_path)
    elif provider in ("ltx", "ltx_desktop", "ovi"):
        # LTX-Desktop app (local FastAPI, port 41954). 'ltx'/'ovi' are legacy
        # aliases kept so existing pods/episodes keep rendering on Desktop.
        return LtxDesktopProvider(pod_config_path)
    elif provider == "ltx_comfyui":
        # LTX-2 via ComfyUI (port 8188) — supports Character LoRAs / node graph.
        from videocreator.infrastructure.engine.providers.ltx_provider import LtxProvider
        return LtxProvider(pod_config_path)
    elif provider == "artlist":
        return ArtlistProvider(pod_config_path)
    elif provider == "elevenlabs_studio":
        return ElevenLabsStudioProvider(pod_config_path)
    else:
        raise ValueError(
            f"VIDEO_PROVIDER '{provider}' no reconocido. Opciones: 'veo', "
            "'ltx_desktop', 'ltx_comfyui', 'artlist', 'elevenlabs_studio'"
        )
