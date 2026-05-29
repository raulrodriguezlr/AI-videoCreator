"""Unit tests for the ProviderRouter domain service (pure logic, no I/O)."""
from __future__ import annotations

from videocreator.domain.services.provider_router import ProviderRouter
from videocreator.domain.value_objects import ProviderPreferences, ProviderSelection, StyleProfile


def test_style_default_used_when_no_explicit_primary() -> None:
    # Arrange
    router = ProviderRouter()
    prefs = ProviderPreferences(primary="")  # empty → fall back to style default

    # Act
    selection = router.select(StyleProfile.CINEMATIC_3D, prefs)

    # Assert
    assert selection.provider == "artlist"
    assert "kling-3.0" in selection.model_hints


def test_explicit_primary_overrides_style_default() -> None:
    # Arrange
    router = ProviderRouter()
    prefs = ProviderPreferences(primary="veo", fallback_chain=["ltx"])

    # Act
    selection = router.select(StyleProfile.ANIME_2D, prefs)

    # Assert — the creator's explicit choice wins over the anime→artlist default
    assert selection.provider == "veo"
    assert selection.fallback_chain == ("ltx",)


def test_pod_model_hints_take_priority_over_style_hints() -> None:
    # Arrange
    router = ProviderRouter()
    prefs = ProviderPreferences(primary="artlist", model_hints=["luma-dream"])

    # Act
    selection = router.select(StyleProfile.CINEMATIC_3D, prefs)

    # Assert
    assert selection.model_hints == ("luma-dream",)


def test_latency_priority_is_propagated_into_params() -> None:
    # Arrange
    router = ProviderRouter()
    prefs = ProviderPreferences(latency_priority="fast")

    # Act
    selection = router.select(StyleProfile.PHOTOREAL_DOC, prefs)

    # Assert
    assert selection.params["latency_priority"] == "fast"


def test_talking_head_routes_to_elevenlabs_studio_with_dub_inline() -> None:
    # Arrange
    router = ProviderRouter()
    prefs = ProviderPreferences(primary="")

    # Act
    selection = router.select(StyleProfile.TALKING_HEAD_AVATAR, prefs)

    # Assert
    assert selection.provider == "elevenlabs_studio"
    assert selection.params.get("dub_inline") is True


def test_chain_dedupes_and_orders_primary_first() -> None:
    # Arrange / Act
    selection = ProviderSelection(provider="artlist", fallback_chain=("veo", "artlist", "ltx"))

    # Assert — primary first, duplicates removed
    assert selection.chain == ("artlist", "veo", "ltx")
