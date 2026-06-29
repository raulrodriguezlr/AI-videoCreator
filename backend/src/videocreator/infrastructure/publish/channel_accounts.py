"""Multi-account OAuth connect/store for the Channels Hub.

One service handles all three platforms. Credentials live in the existing
Fernet vault, scoped per account so a user can connect N accounts per platform:
the vault `provider` key is ``{platform}:{account_id}:{secret}``.

Browser login:
- YouTube reuses google's ``InstalledAppFlow.run_local_server`` (refresh token).
- TikTok / Instagram use a generic Authorization-Code flow with a local redirect
  listener (open browser → user logs in → callback caught locally → code
  exchanged for tokens). Both flows are injectable so tests never hit the network.

Distribution is local, so client_id/secret are the user's own app credentials,
passed into ``connect`` and stored alongside the tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from videocreator.domain.entities import PublishAccount
from videocreator.domain.ports import PublishAccountRepository, SecretVaultPort
from videocreator.domain.value_objects import AccountStatus, PublishPlatform
from videocreator.shared.errors import ProviderError
from videocreator.shared.ids import UserId, new_publish_account_id
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# Vault secret names stored per account.
SECRET_REFRESH = "refresh_token"
SECRET_ACCESS = "access_token"
SECRET_CLIENT_ID = "client_id"
SECRET_CLIENT_SECRET = "client_secret"


@dataclass(frozen=True)
class PlatformOAuth:
    """Authorize/token endpoints + scopes for an auth-code platform."""

    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]


# Real endpoints; only used when the user supplies their own approved app creds.
PLATFORM_OAUTH: dict[PublishPlatform, PlatformOAuth] = {
    PublishPlatform.TIKTOK: PlatformOAuth(
        authorize_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=("user.info.basic", "video.publish", "video.upload"),
    ),
    PublishPlatform.INSTAGRAM: PlatformOAuth(
        authorize_url="https://api.instagram.com/oauth/authorize",
        token_url="https://api.instagram.com/oauth/access_token",
        scopes=("instagram_business_basic", "instagram_business_content_publish"),
    ),
}

#: Token bundle returned by a connect flow: refresh/access tokens + display.
TokenBundle = dict[str, Any]

#: (client_id, client_secret) -> TokenBundle. Injectable per platform for tests.
YouTubeFlow = Callable[[str, str], TokenBundle]
AuthCodeFlow = Callable[[PublishPlatform, str, str, PlatformOAuth], TokenBundle]


def _key(platform: PublishPlatform, account_id: str, secret: str) -> str:
    return f"{platform.value}:{account_id}:{secret}"


class OAuthAccountService:
    """Connect, list, and disconnect publishing accounts across platforms."""

    def __init__(
        self,
        vault: SecretVaultPort,
        account_repo: PublishAccountRepository,
        *,
        youtube_flow: YouTubeFlow | None = None,
        auth_code_flow: AuthCodeFlow | None = None,
    ) -> None:
        self._vault = vault
        self._repo = account_repo
        self._youtube_flow = youtube_flow
        self._auth_code_flow = auth_code_flow

    async def connect(
        self,
        user_id: UserId,
        platform: PublishPlatform,
        *,
        client_id: str,
        client_secret: str,
    ) -> PublishAccount:
        """Run the browser login flow and persist a new account + its tokens."""
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")

        if platform is PublishPlatform.YOUTUBE:
            bundle = self._run_youtube_flow(client_id, client_secret)
        else:
            bundle = self._run_auth_code_flow(platform, client_id, client_secret)

        account = PublishAccount(
            id=new_publish_account_id(),
            user_id=user_id,
            platform=platform,
            display_name=str(bundle.get("display_name") or platform.value.title()),
            handle=bundle.get("handle"),
            status=AccountStatus.CONNECTED,
        )
        await self._repo.save(account)

        aid = str(account.id)
        if bundle.get("refresh_token"):
            await self._vault.set_secret(user_id, _key(platform, aid, SECRET_REFRESH), bundle["refresh_token"])
        if bundle.get("access_token"):
            await self._vault.set_secret(user_id, _key(platform, aid, SECRET_ACCESS), bundle["access_token"])
        await self._vault.set_secret(user_id, _key(platform, aid, SECRET_CLIENT_ID), client_id)
        await self._vault.set_secret(user_id, _key(platform, aid, SECRET_CLIENT_SECRET), client_secret)
        log.info("channel.connected", platform=platform.value, account_id=aid)
        return account

    async def list_accounts(self, user_id: UserId) -> list[PublishAccount]:
        return await self._repo.list_for_user(user_id)

    async def disconnect(self, account: PublishAccount) -> None:
        aid = str(account.id)
        for secret in (SECRET_REFRESH, SECRET_ACCESS, SECRET_CLIENT_ID, SECRET_CLIENT_SECRET):
            await self._vault.delete_secret(account.user_id, _key(account.platform, aid, secret))
        await self._repo.delete(account.id)
        log.info("channel.disconnected", platform=account.platform.value, account_id=aid)

    async def credentials(self, account: PublishAccount) -> TokenBundle:
        """Return the stored token bundle for an account (for upload)."""
        aid = str(account.id)
        bundle: TokenBundle = {}
        for secret in (SECRET_REFRESH, SECRET_ACCESS, SECRET_CLIENT_ID, SECRET_CLIENT_SECRET):
            val = await self._vault.get_secret(account.user_id, _key(account.platform, aid, secret))
            if val is not None:
                bundle[secret] = val
        if not bundle:
            raise ProviderError(f"{account.platform.value} account not connected")
        return bundle

    # -- flow runners --------------------------------------------------------
    def _run_youtube_flow(self, client_id: str, client_secret: str) -> TokenBundle:
        if self._youtube_flow is not None:
            return self._youtube_flow(client_id, client_secret)
        return _default_youtube_flow(client_id, client_secret)

    def _run_auth_code_flow(
        self, platform: PublishPlatform, client_id: str, client_secret: str,
    ) -> TokenBundle:
        cfg = PLATFORM_OAUTH.get(platform)
        if cfg is None:
            raise ProviderError(f"no OAuth config for {platform.value}")
        if self._auth_code_flow is not None:
            return self._auth_code_flow(platform, client_id, client_secret, cfg)
        return _default_auth_code_flow(platform, client_id, client_secret, cfg)


# ---- default (real) flow implementations -----------------------------------
def _default_youtube_flow(client_id: str, client_secret: str) -> TokenBundle:
    """Reuse the existing YouTube installed-app browser flow."""
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - dep guard
        raise ProviderError("google-auth-oauthlib not installed") from e
    from videocreator.infrastructure.publish.youtube_oauth import SCOPES

    flow = InstalledAppFlow.from_client_config(client_config, list(SCOPES))
    creds = flow.run_local_server(port=0, open_browser=True)
    refresh = getattr(creds, "refresh_token", None)
    if not refresh:
        raise ProviderError(
            "OAuth completed but no refresh token issued — revoke at "
            "myaccount.google.com/permissions and retry"
        )
    return {"refresh_token": refresh}


def _default_auth_code_flow(
    platform: PublishPlatform, client_id: str, client_secret: str, cfg: PlatformOAuth,
) -> TokenBundle:  # pragma: no cover - network/browser, exercised manually
    """Generic Authorization-Code flow with a local redirect listener.

    Opens the browser to the platform's authorize URL, catches the callback on
    a free localhost port, exchanges the code for tokens. Requires the user's
    own approved app credentials; raises cleanly otherwise.
    """
    import http.server
    import secrets as _secrets
    import socket
    import threading
    import urllib.parse
    import webbrowser

    import httpx  # lazy

    # free port for the redirect listener
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = _secrets.token_urlsafe(16)
    captured: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = urllib.parse.urlparse(self.path).query
            params = dict(urllib.parse.parse_qsl(q))
            captured.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Conectado. Puedes cerrar esta ventana.</h2>")

        def log_message(self, *_a: Any) -> None:  # silence
            return

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    auth_params = urllib.parse.urlencode({
        "client_key" if platform is PublishPlatform.TIKTOK else "client_id": client_id,
        "response_type": "code",
        "scope": ",".join(cfg.scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    })
    webbrowser.open(f"{cfg.authorize_url}?{auth_params}")
    # handle_request serves exactly one request (the OAuth callback)
    threading.Thread(target=server.handle_request, daemon=True).start()
    import time as _time
    try:
        for _ in range(600):  # ~60s
            if captured:
                break
            _time.sleep(0.1)
        if captured.get("state") != state or "code" not in captured:
            raise ProviderError(f"{platform.value} OAuth did not return a valid code")

        resp = httpx.post(cfg.token_url, data={
            "client_key" if platform is PublishPlatform.TIKTOK else "client_id": client_id,
            "client_secret": client_secret,
            "code": captured["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    finally:
        server.server_close()  # release the bound port on every path

    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not access and not refresh:
        # Some platforms return HTTP 200 with an error payload — treat a
        # tokenless response as a failed connect rather than a live account.
        raise ProviderError(
            f"{platform.value} token exchange returned no token: {data.get('error') or data}"
        )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "display_name": data.get("display_name"),
    }


__all__ = [
    "OAuthAccountService",
    "PlatformOAuth",
    "PLATFORM_OAUTH",
    "SECRET_ACCESS",
    "SECRET_CLIENT_ID",
    "SECRET_CLIENT_SECRET",
    "SECRET_REFRESH",
]
