"""Tests for YouTube OAuth service — fake flow + in-memory vault, no Google."""
from __future__ import annotations

from typing import Any

import pytest

from videocreator.infrastructure.publish.youtube_oauth import (
    VAULT_CLIENT_ID,
    VAULT_CLIENT_SECRET,
    VAULT_REFRESH_TOKEN,
    YouTubeOAuthService,
)
from videocreator.shared.errors import ProviderError
from videocreator.shared.ids import UserId

USER = UserId("u1")


class FakeVault:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    async def get_secret(self, user_id: UserId, provider: str) -> str | None:
        return self._store.get((str(user_id), provider))

    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None:
        self._store[(str(user_id), provider)] = value

    async def delete_secret(self, user_id: UserId, provider: str) -> None:
        self._store.pop((str(user_id), provider), None)

    async def list_providers(self, user_id: UserId) -> list[str]:
        return [p for (u, p) in self._store if u == str(user_id)]


class FakeCredentials:
    def __init__(self, refresh_token: str | None) -> None:
        self.refresh_token = refresh_token


class FakeFlow:
    def __init__(self, refresh_token: str | None = "rt-123",
                 error: Exception | None = None) -> None:
        self._refresh_token = refresh_token
        self._error = error
        self.config: dict[str, Any] | None = None
        self.scopes: list[str] | None = None

    def run_local_server(self, **kwargs: Any) -> FakeCredentials:
        if self._error:
            raise self._error
        return FakeCredentials(self._refresh_token)


def _service(vault: FakeVault, flow: FakeFlow) -> YouTubeOAuthService:
    def factory(config: dict[str, Any], scopes: list[str]) -> FakeFlow:
        flow.config = config
        flow.scopes = scopes
        return flow

    return YouTubeOAuthService(vault, flow_factory=factory)


class TestConnect:
    @pytest.mark.asyncio
    async def test_stores_credentials_in_vault(self) -> None:
        vault = FakeVault()
        service = _service(vault, FakeFlow())
        result = await service.connect(USER, client_id="cid", client_secret="cs")
        assert result.connected is True
        assert await vault.get_secret(USER, VAULT_REFRESH_TOKEN) == "rt-123"
        assert await vault.get_secret(USER, VAULT_CLIENT_ID) == "cid"
        assert await vault.get_secret(USER, VAULT_CLIENT_SECRET) == "cs"

    @pytest.mark.asyncio
    async def test_flow_gets_upload_and_analytics_scopes(self) -> None:
        flow = FakeFlow()
        await _service(FakeVault(), flow).connect(
            USER, client_id="cid", client_secret="cs")
        assert flow.scopes is not None
        assert any("youtube.upload" in s for s in flow.scopes)
        assert any("yt-analytics" in s for s in flow.scopes)

    @pytest.mark.asyncio
    async def test_missing_refresh_token_raises(self) -> None:
        service = _service(FakeVault(), FakeFlow(refresh_token=None))
        with pytest.raises(ProviderError, match="refresh token"):
            await service.connect(USER, client_id="cid", client_secret="cs")

    @pytest.mark.asyncio
    async def test_flow_error_wrapped(self) -> None:
        service = _service(FakeVault(), FakeFlow(error=RuntimeError("denied")))
        with pytest.raises(ProviderError):
            await service.connect(USER, client_id="cid", client_secret="cs")

    @pytest.mark.asyncio
    async def test_empty_client_id_rejected(self) -> None:
        service = _service(FakeVault(), FakeFlow())
        with pytest.raises(ValueError):
            await service.connect(USER, client_id="", client_secret="cs")


class TestStatusAndDisconnect:
    @pytest.mark.asyncio
    async def test_status_lifecycle(self) -> None:
        vault = FakeVault()
        service = _service(vault, FakeFlow())
        assert (await service.status(USER)).connected is False
        await service.connect(USER, client_id="cid", client_secret="cs")
        assert (await service.status(USER)).connected is True
        await service.disconnect(USER)
        assert (await service.status(USER)).connected is False
        assert await vault.get_secret(USER, VAULT_CLIENT_ID) is None

    @pytest.mark.asyncio
    async def test_build_credentials_requires_connection(self) -> None:
        service = _service(FakeVault(), FakeFlow())
        with pytest.raises(ProviderError, match="not connected"):
            await service.build_credentials(USER)
