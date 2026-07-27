"""YouTube OAuth2 one-time flow — refresh token into the vault (§16.14).

Local-first: `InstalledAppFlow.run_local_server` opens the user's browser on
this machine once; afterwards `youtube_publisher.build_credentials` rebuilds
Credentials from the stored refresh token forever. google-auth-oauthlib is a
lazy import; the flow factory is injectable so tests never touch Google.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from videocreator.domain.ports import SecretVaultPort
from videocreator.shared.errors import ProviderError
from videocreator.shared.ids import UserId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)

#: Vault keys where the OAuth artifacts live.
VAULT_REFRESH_TOKEN = "youtube_refresh_token"
VAULT_CLIENT_ID = "youtube_client_id"
VAULT_CLIENT_SECRET = "youtube_client_secret"

FlowFactory = Callable[[dict[str, Any], list[str]], Any]


@dataclass(frozen=True)
class OAuthResult:
    connected: bool
    has_refresh_token: bool


class YouTubeOAuthService:
    """Run the OAuth consent flow once and persist credentials in the vault."""

    def __init__(
        self,
        vault: SecretVaultPort,
        *,
        flow_factory: FlowFactory | None = None,
    ) -> None:
        self._vault = vault
        self._flow_factory = flow_factory

    async def connect(
        self,
        user_id: UserId,
        *,
        client_id: str,
        client_secret: str,
    ) -> OAuthResult:
        """Run the local-server consent flow; store refresh token + client pair."""
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")

        flow = self._build_flow(client_id, client_secret)
        try:
            credentials = flow.run_local_server(port=0, open_browser=True)
        except Exception as e:
            log.error("youtube_oauth.flow_failed", error=str(e))
            raise ProviderError(f"YouTube OAuth flow failed: {e}") from e

        refresh_token = getattr(credentials, "refresh_token", None)
        if not refresh_token:
            # Google only issues a refresh token on first consent (or with
            # prompt=consent) — without it we cannot publish unattended.
            raise ProviderError(
                "OAuth completed but no refresh token was issued — revoke the "
                "app at myaccount.google.com/permissions and retry"
            )

        await self._vault.set_secret(user_id, VAULT_REFRESH_TOKEN, refresh_token)
        await self._vault.set_secret(user_id, VAULT_CLIENT_ID, client_id)
        await self._vault.set_secret(user_id, VAULT_CLIENT_SECRET, client_secret)
        log.info("youtube_oauth.connected", user_id=str(user_id))
        return OAuthResult(connected=True, has_refresh_token=True)

    async def status(self, user_id: UserId) -> OAuthResult:
        token = await self._vault.get_secret(user_id, VAULT_REFRESH_TOKEN)
        return OAuthResult(connected=token is not None,
                           has_refresh_token=token is not None)

    async def disconnect(self, user_id: UserId) -> None:
        for key in (VAULT_REFRESH_TOKEN, VAULT_CLIENT_ID, VAULT_CLIENT_SECRET):
            await self._vault.delete_secret(user_id, key)
        log.info("youtube_oauth.disconnected", user_id=str(user_id))

    async def build_credentials(self, user_id: UserId) -> Any:
        """Rebuild google Credentials from the vault for upload/analytics."""
        refresh_token = await self._vault.get_secret(user_id, VAULT_REFRESH_TOKEN)
        client_id = await self._vault.get_secret(user_id, VAULT_CLIENT_ID)
        client_secret = await self._vault.get_secret(user_id, VAULT_CLIENT_SECRET)
        if not (refresh_token and client_id and client_secret):
            raise ProviderError(
                "YouTube is not connected — run the OAuth flow first"
            )
        from videocreator.infrastructure.publish.youtube_publisher import (
            build_credentials,
        )
        return build_credentials(
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )

    def _build_flow(self, client_id: str, client_secret: str) -> Any:
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        if self._flow_factory is not None:
            return self._flow_factory(client_config, list(SCOPES))
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderError(
                "google-auth-oauthlib not installed — "
                "pip install google-auth-oauthlib"
            ) from e
        return InstalledAppFlow.from_client_config(client_config, list(SCOPES))


__all__ = [
    "SCOPES",
    "VAULT_CLIENT_ID",
    "VAULT_CLIENT_SECRET",
    "VAULT_REFRESH_TOKEN",
    "OAuthResult",
    "YouTubeOAuthService",
]
