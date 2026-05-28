"""
Provider Factory — Returns the correct video provider based on variables.py config.

Usage:
    from src.providers import get_provider
    provider = get_provider("pods/kids_story/config.json")
"""

from src.variables import VIDEO_PROVIDER
from src.providers.veo_provider import VeoProvider
from src.providers.ltx_provider import LtxProvider


def get_provider(pod_config_path: str):
    """
    Factory function that returns the correct video provider
    based on VIDEO_PROVIDER setting in variables.py.

    Args:
        pod_config_path: Path to the pod's config.json file.

    Returns:
        An instance of BaseVideoProvider (VeoProvider or LtxProvider).

    Raises:
        ValueError: If VIDEO_PROVIDER is not recognized.
    """
    if VIDEO_PROVIDER == "veo":
        return VeoProvider(pod_config_path)

    elif VIDEO_PROVIDER in ("ltx", "ovi"):  # "ovi" kept for backward compat
        return LtxProvider(pod_config_path)

    else:
        raise ValueError(
            f"VIDEO_PROVIDER '{VIDEO_PROVIDER}' no reconocido. "
            f"Opciones válidas: 'veo', 'ltx'"
        )
