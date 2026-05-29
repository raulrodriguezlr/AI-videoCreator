"""Unit tests for ArtlistModelSelector (pure selection logic over a catalog)."""
from __future__ import annotations

import pytest

from videocreator.domain.services.artlist_model_selector import ArtlistModelSelector
from videocreator.domain.value_objects import Capability, ModelHandle, StyleProfile
from videocreator.shared.errors import ArtlistModelUnavailableError

T2V = frozenset({Capability.TEXT_TO_VIDEO})


def _catalog() -> list[ModelHandle]:
    return [
        ModelHandle(
            id="kling-3.0",
            family="kling",
            capabilities=frozenset({Capability.TEXT_TO_VIDEO, Capability.REF_IMAGE}),
            max_duration_s=10,
            max_resolution=(1920, 1080),
            cost_per_second_usd=0.18,
            latency_p95_s=70,
        ),
        ModelHandle(
            id="veo-2",
            family="veo",
            capabilities=T2V,
            max_duration_s=8,
            max_resolution=(1920, 1080),
            cost_per_second_usd=0.25,
            latency_p95_s=90,
        ),
        ModelHandle(
            id="minimax-hailuo",
            family="minimax",
            capabilities=T2V,
            max_duration_s=6,
            max_resolution=(1280, 720),
            cost_per_second_usd=0.08,
            latency_p95_s=45,
        ),
        ModelHandle(
            id="pixverse-v3",
            family="pixverse",
            capabilities=T2V,
            max_duration_s=8,
            max_resolution=(1280, 720),
            cost_per_second_usd=0.10,
            latency_p95_s=50,
        ),
    ]


def test_cinematic_balanced_prefers_kling() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act
    chosen = selector.select(
        _catalog(), style_profile=StyleProfile.CINEMATIC_3D, duration_s=5.0
    )

    # Assert — kling is the top-ranked family for cinematic_3d
    assert chosen.id == "kling-3.0"


def test_anime_balanced_prefers_pixverse() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act
    chosen = selector.select(_catalog(), style_profile=StyleProfile.ANIME_2D, duration_s=4.0)

    # Assert
    assert chosen.id == "pixverse-v3"


def test_fast_latency_picks_lowest_p95() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act
    chosen = selector.select(
        _catalog(),
        style_profile=StyleProfile.CINEMATIC_3D,
        duration_s=5.0,
        latency_priority="fast",
    )

    # Assert — minimax has the lowest latency_p95_s (45s)
    assert chosen.id == "minimax-hailuo"


def test_budget_filters_out_expensive_models() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act — $0.5 budget over 5s = $0.10/s cap; only the two cheapest survive
    chosen = selector.select(
        _catalog(),
        style_profile=StyleProfile.STOCK_MONTAGE,
        duration_s=5.0,
        budget_usd=0.5,
    )

    # Assert — minimax (cheapest, top stock family) wins
    assert chosen.id == "minimax-hailuo"


def test_duration_exceeding_all_models_raises() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act / Assert
    with pytest.raises(ArtlistModelUnavailableError):
        selector.select(_catalog(), style_profile=StyleProfile.CINEMATIC_3D, duration_s=60.0)


def test_required_capability_filters_catalog() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act — only kling exposes REF_IMAGE
    chosen = selector.select(
        _catalog(),
        style_profile=StyleProfile.CINEMATIC_3D,
        duration_s=5.0,
        required=frozenset({Capability.REF_IMAGE}),
    )

    # Assert
    assert chosen.id == "kling-3.0"


def test_prefer_models_hint_wins_when_available() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act
    chosen = selector.select(
        _catalog(),
        style_profile=StyleProfile.CINEMATIC_3D,
        duration_s=5.0,
        prefer_models=("veo-2",),
    )

    # Assert — explicit hint overrides family ranking
    assert chosen.id == "veo-2"


def test_empty_catalog_raises() -> None:
    # Arrange
    selector = ArtlistModelSelector()

    # Act / Assert
    with pytest.raises(ArtlistModelUnavailableError):
        selector.select([], style_profile=StyleProfile.CINEMATIC_3D, duration_s=5.0)
