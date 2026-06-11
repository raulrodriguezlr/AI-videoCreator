"""The DI container must wire DB-backed persistence + filesystem storage in
server mode too (single-node Postgres + local disk), not just local mode.
Only object storage (s3://) is expected to remain unimplemented.
"""
from __future__ import annotations

import pytest

from videocreator.infrastructure.container import Container
from videocreator.shared.config import Settings


def _server_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_mode": "server",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "storage_url": "file://./var/storage",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_server_mode_wires_sql_repositories() -> None:
    c = Container(_server_settings())

    assert type(c.pod_repo()).__name__ == "SqlPodRepository"
    assert type(c.episode_repo()).__name__ == "SqlEpisodeRepository"
    assert type(c.user_repo()).__name__ == "SqlUserRepository"


def test_server_mode_uses_filesystem_storage() -> None:
    c = Container(_server_settings())
    assert type(c.storage()).__name__ == "LocalFileStorage"


def test_object_storage_still_unimplemented() -> None:
    c = Container(_server_settings(storage_url="s3://bucket/prefix"))
    with pytest.raises(NotImplementedError, match="s3://"):
        c.storage()


def test_available_provider_names_is_superset() -> None:
    """The catalog must include KNOWN_VIDEO_PROVIDERS, the SDK registry ids
    (loaded from providers.d/), and the configured legacy engine default."""
    pytest.importorskip("yaml")
    c = Container(_server_settings(video_provider_default="veo"))

    names = c.available_provider_names()

    # KNOWN_VIDEO_PROVIDERS
    assert "artlist" in names
    assert "elevenlabs_studio" in names
    # SDK registry ids (providers.d/*/provider.yaml)
    sdk_ids = {lp.manifest.id for lp in c.provider_registry().providers.values()}
    assert sdk_ids  # sanity: registry actually discovered something
    assert sdk_ids <= names
    # legacy engine default
    assert "veo" in names


def test_available_provider_names_recomputed_each_call() -> None:
    """Not cached — a hot-reloaded registry must be reflected immediately."""
    pytest.importorskip("yaml")
    c = Container(_server_settings(video_provider_default="ltx"))

    before = c.available_provider_names()
    assert "ltx" in before
    assert "veo" not in before

    # Drop a provider from the live registry (one that isn't *also* in
    # KNOWN_VIDEO_PROVIDERS) and confirm the next call sees it disappear.
    registry = c.provider_registry()
    candidates = [pid for pid in registry.providers if pid not in c.KNOWN_VIDEO_PROVIDERS]
    if candidates:
        removed_id = candidates[0]
        registry._catalog.pop(removed_id)
        after = c.available_provider_names()
        assert removed_id not in after
