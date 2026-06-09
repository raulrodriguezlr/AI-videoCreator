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
