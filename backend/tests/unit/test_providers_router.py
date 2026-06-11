"""Tests for the providers router — broken providers must stay *visible* in
the catalog (available=False + status_detail), never silently dropped, and
each failure must be logged.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pytest
from structlog.testing import capture_logs

import videocreator.interfaces.rest.routers.providers as providers_router
from videocreator.infrastructure.container import Container
from videocreator.infrastructure.providers.artlist_provider import ArtlistProvider
from videocreator.interfaces.rest.routers.providers import (
    _provider_models,
    providers_catalog,
)
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError


class _FakeStorage:
    """Minimal StoragePort stand-in."""

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        return key

    async def get(self, bucket: str, key: str) -> bytes:
        return b""

    async def open_path(self, bucket: str, key: str) -> Path:
        return Path(key)

    async def delete(self, bucket: str, key: str) -> None: ...

    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        return f"file://{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        return []


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "storage_url": "file://./var/storage",
        # No keys configured — providers report unavailable, not raise, by
        # default. The tests below force a raise via monkeypatching.
        "artlist_api_token": None,
        "elevenlabs_api_key": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _BoomProvider:
    """A `VideoProviderPort`-shaped stand-in whose `.availability()` raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def availability(self):  # type: ignore[no-untyped-def]
        raise self._exc

    async def catalog(self):  # type: ignore[no-untyped-def]
        raise self._exc


async def _no_engine_entries(container: Container) -> list:  # type: ignore[type-arg]
    """Stub for `_engine_entries` — avoids real network calls to LTX-Desktop /
    ComfyUI in unit tests; the engine entries aren't under test here."""
    return []


@pytest.mark.asyncio
async def test_broken_provider_stays_in_catalog_with_status_detail(monkeypatch) -> None:
    """A provider whose adapter raises must still appear in the catalog —
    flagged unavailable with a `status_detail`, not silently dropped."""
    container = Container(_settings())
    boom = ProviderError("artlist upstream is on fire and this message is short")

    def _video_provider(name: str):  # type: ignore[no-untyped-def]
        if name == "artlist":
            return _BoomProvider(boom)
        raise NotImplementedError(name)

    monkeypatch.setattr(container, "video_provider", _video_provider)
    monkeypatch.setattr(providers_router, "_engine_entries", _no_engine_entries)

    with capture_logs() as logs:
        entries = await providers_catalog(container)

    artlist = next(e for e in entries if e.name == "artlist")
    assert artlist.available is False
    assert artlist.status_detail is not None
    assert str(boom) in artlist.status_detail
    # The other known provider must still be processed normally.
    assert any(e.name == "elevenlabs_studio" for e in entries)

    warnings = [log for log in logs if log.get("log_level") == "warning"]
    assert any(
        log.get("event") == "providers.availability_failed" and log.get("provider") == "artlist"
        for log in warnings
    )


@pytest.mark.asyncio
async def test_status_detail_is_truncated(monkeypatch) -> None:
    container = Container(_settings())
    long_message = "x" * 500
    boom = ProviderError(long_message)

    def _video_provider(name: str):  # type: ignore[no-untyped-def]
        if name == "artlist":
            return _BoomProvider(boom)
        raise NotImplementedError(name)

    monkeypatch.setattr(container, "video_provider", _video_provider)
    monkeypatch.setattr(providers_router, "_engine_entries", _no_engine_entries)

    entries = await providers_catalog(container)
    artlist = next(e for e in entries if e.name == "artlist")
    assert artlist.status_detail is not None
    assert len(artlist.status_detail) <= 200


@pytest.mark.asyncio
async def test_provider_models_falls_back_and_logs_on_error(monkeypatch) -> None:
    """`_provider_models` must log (not silently swallow) when fetching the
    Artlist catalog fails, and still return the static fallback catalog."""
    container = Container(_settings())
    artlist = ArtlistProvider(container.settings, _FakeStorage())
    boom = ProviderError("artlist catalog endpoint unreachable")

    async def _broken_catalog(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise boom

    monkeypatch.setattr(artlist, "catalog", _broken_catalog)
    monkeypatch.setattr(container, "video_provider", lambda name: artlist)

    with capture_logs() as logs:
        models = await _provider_models("artlist", container)

    assert "kling-3.0" in models  # static catalog fallback

    warnings = [log for log in logs if log.get("log_level") == "warning"]
    assert any(
        log.get("event") == "providers.models_fetch_failed" and log.get("provider") == "artlist"
        for log in warnings
    )
