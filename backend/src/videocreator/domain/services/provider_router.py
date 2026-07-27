"""ProviderRouter — decouples *style* (what the creator wants) from *provider*
(which account/API runs) from *model* (which concrete engine).

This is pure decision logic: given a pod's `style_profile` plus its
`ProviderPreferences`, it returns a `ProviderSelection` describing which
provider to try first, an ordered fallback chain, and provider-specific hints.

Per Plan Maestro §B.1.3, changing Veo→Sora or Kling 3.0→4.0 must not require
touching pods — only this table (or the pod's explicit `provider_preferences`).
"""
from __future__ import annotations

from videocreator.domain.value_objects import (
    ProviderPreferences,
    ProviderSelection,
    StyleProfile,
)

# Default mapping from a semantic style to a provider + model hints.
# A pod's explicit `provider_preferences.primary` always overrides this.
_STYLE_DEFAULTS: dict[StyleProfile, ProviderSelection] = {
    StyleProfile.CINEMATIC_3D: ProviderSelection(
        provider="artlist",
        fallback_chain=("veo", "ltx_desktop"),
        model_hints=("kling-3.0", "veo-2"),
    ),
    StyleProfile.ANIME_2D: ProviderSelection(
        provider="artlist",
        fallback_chain=("ltx_desktop",),
        model_hints=("pixverse-v3",),
    ),
    StyleProfile.PHOTOREAL_DOC: ProviderSelection(
        provider="veo",
        fallback_chain=("artlist",),
        model_hints=("veo-2", "kling-3.0"),
        params={"quality": "ultra"},
    ),
    StyleProfile.TALKING_HEAD_AVATAR: ProviderSelection(
        provider="elevenlabs_studio",
        fallback_chain=("artlist",),
        params={"dub_inline": True},
    ),
    StyleProfile.STOCK_MONTAGE: ProviderSelection(
        provider="artlist",
        fallback_chain=("ltx_desktop",),
        model_hints=("minimax-hailuo",),
        params={"prefer_cheapest": True},
    ),
    StyleProfile.KIDS_3D: ProviderSelection(
        provider="artlist",
        fallback_chain=("veo", "ltx_desktop"),
        model_hints=("kling-3.0",),
    ),
}

_FALLBACK_SELECTION = ProviderSelection(provider="veo", fallback_chain=("ltx_desktop",))


class ProviderRouter:
    """Resolves `(StyleProfile, ProviderPreferences)` → `ProviderSelection`."""

    def __init__(self, style_defaults: dict[StyleProfile, ProviderSelection] | None = None) -> None:
        self._defaults = style_defaults or _STYLE_DEFAULTS

    def select(
        self,
        style_profile: StyleProfile,
        preferences: ProviderPreferences,
    ) -> ProviderSelection:
        """Pick a provider for a pod.

        Precedence:
        1. An explicit `preferences.primary` (non-empty) wins — the creator
           opted into a specific provider.
        2. Otherwise fall back to the style→provider default table.
        3. Otherwise a safe global default.

        In all cases, pod-level `model_hints`/`fallback_chain` augment the result
        so per-pod overrides compose with style defaults.
        """
        base = self._defaults.get(style_profile, _FALLBACK_SELECTION)

        provider = preferences.primary or base.provider
        fallback = tuple(preferences.fallback_chain) or base.fallback_chain
        # Pod hints take priority; style hints fill in when the pod gives none.
        hints = tuple(preferences.model_hints) or base.model_hints

        params = dict(base.params)
        params["latency_priority"] = preferences.latency_priority

        return ProviderSelection(
            provider=provider,
            fallback_chain=fallback,
            model_hints=hints,
            params=params,
        )


__all__ = ["ProviderRouter"]
