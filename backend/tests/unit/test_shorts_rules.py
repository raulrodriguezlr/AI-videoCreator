"""Unit tests for the shorts rule-book loader and platform resolution."""
from __future__ import annotations

import pytest

from videocreator.domain.value_objects import PlatformRule, ShortsRules
from videocreator.infrastructure.video.shorts_rules import (
    default_shorts_rules,
    load_shorts_rules,
)


def test_bundled_rules_cover_three_platforms() -> None:
    # Act
    rules = default_shorts_rules()

    # Assert
    platforms = {r.platform for r in rules.platforms}
    assert {"shorts", "reels", "tiktok"} <= platforms
    assert rules.default_platform == "shorts"


def test_load_shorts_rules_validates_frame_size() -> None:
    # Act — the bundled file is parsed and validated via Pydantic
    rules = load_shorts_rules()
    shorts = rules.rule_for("shorts")

    # Assert
    assert (shorts.width, shorts.height) == (1080, 1920)
    assert shorts.aspect == "9:16"


def test_rule_for_unknown_platform_falls_back_to_default() -> None:
    # Arrange
    rules = ShortsRules(
        default_platform="shorts",
        platforms=(
            PlatformRule(platform="shorts", max_duration_s=60.0),
            PlatformRule(platform="reels", max_duration_s=90.0),
        ),
    )

    # Act
    resolved = rules.rule_for("nonexistent")

    # Assert
    assert resolved.platform == "shorts"


def test_rule_for_empty_rulebook_raises() -> None:
    rules = ShortsRules(default_platform="shorts", platforms=())
    with pytest.raises(ValueError, match="no platforms"):
        rules.rule_for("shorts")
