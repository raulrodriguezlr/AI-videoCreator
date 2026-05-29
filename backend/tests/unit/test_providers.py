"""Adapter tests for the new video providers using respx-mocked HTTP.

These verify availability/catalog behaviour and graceful degradation without
making real network calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import httpx
import pytest
import respx

from videocreator.infrastructure.providers.artlist_provider import (
    _STATIC_CATALOG,
    ArtlistProvider,
)
from videocreator.infrastructure.providers.elevenlabs_studio_provider import (
    ElevenLabsStudioProvider,
)
from videocreator.shared.config import Settings


class _FakeStorage:
    """Minimal StoragePort stand-in — only `put` is exercised here."""

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
        "artlist_api_token": "test-token",
        "elevenlabs_api_key": "test-key",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def test_elevenlabs_studio_unavailable_without_key() -> None:
    # Arrange
    provider = ElevenLabsStudioProvider(_settings(elevenlabs_api_key=None), _FakeStorage())

    # Act
    health = await provider.availability()

    # Assert
    assert health.available is False
    assert "ELEVENLABS_API_KEY" in (health.message or "")


@respx.mock
async def test_elevenlabs_studio_available_when_user_endpoint_ok() -> None:
    # Arrange
    respx.get("https://api.elevenlabs.io/v1/user").mock(
        return_value=httpx.Response(200, json={"subscription": {"tier": "creator"}})
    )
    provider = ElevenLabsStudioProvider(_settings(), _FakeStorage())

    # Act
    health = await provider.availability()
    await provider.aclose()

    # Assert
    assert health.available is True
    assert health.cost_per_second_usd == pytest.approx(0.30)


async def test_artlist_unavailable_without_token() -> None:
    # Arrange
    provider = ArtlistProvider(_settings(artlist_api_token=None), _FakeStorage())

    # Act
    health = await provider.availability()

    # Assert
    assert health.available is False


@respx.mock
async def test_artlist_catalog_falls_back_to_static_on_http_error() -> None:
    # Arrange
    respx.get("https://api.artlist.io/v1/models").mock(return_value=httpx.Response(500))
    provider = ArtlistProvider(_settings(), _FakeStorage())

    # Act
    catalog = await provider.catalog(force_refresh=True)
    await provider.aclose()

    # Assert — degrade gracefully to the bundled static catalog
    assert len(catalog) == len(_STATIC_CATALOG)
    assert any(m.id == "kling-3.0" for m in catalog)


@respx.mock
async def test_artlist_catalog_parses_live_models() -> None:
    # Arrange
    respx.get("https://api.artlist.io/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {
                        "id": "kling-4.0",
                        "family": "kling",
                        "capabilities": ["text_to_video", "ref_image"],
                        "max_duration_s": 12,
                        "max_resolution": [3840, 2160],
                        "cost_per_second_usd": 0.22,
                        "latency_p95_s": 80,
                        "strengths": ["photoreal"],
                    }
                ]
            },
        )
    )
    provider = ArtlistProvider(_settings(), _FakeStorage())

    # Act
    catalog = await provider.catalog(force_refresh=True)
    await provider.aclose()

    # Assert
    assert len(catalog) == 1
    assert catalog[0].id == "kling-4.0"
    assert catalog[0].max_resolution == (3840, 2160)
