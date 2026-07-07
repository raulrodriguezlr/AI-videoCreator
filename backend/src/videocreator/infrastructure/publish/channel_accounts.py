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

Token hygiene: `credentials()` eagerly refreshes the access token before an
upload uses it (YouTube via `youtube_publisher.build_credentials`, TikTok via
its `/oauth/token/` refresh endpoint), persisting the fresh token in the vault.
A refresh failure (revoked/expired token) marks the account
``AccountStatus.EXPIRED`` and raises a clear `ProviderError` — instead of the
upload failing opaquely with whatever the platform API happened to return.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from videocreator.domain.entities import PublishAccount
from videocreator.domain.ports import PublishAccountRepository, SecretVaultPort
from videocreator.domain.value_objects import AccountStatus, PublishPlatform
from videocreator.infrastructure.publish.youtube_publisher import build_credentials
from videocreator.shared.errors import ProviderError
from videocreator.shared.ids import UserId, new_publish_account_id
from videocreator.shared.logging import get_logger
from videocreator.shared.time import utcnow

log = get_logger(__name__)

# Vault secret names stored per account.
SECRET_REFRESH = "refresh_token"
SECRET_ACCESS = "access_token"
SECRET_CLIENT_ID = "client_id"
SECRET_CLIENT_SECRET = "client_secret"
#: Instagram Business account id (Graph API `/{ig_user_id}/media`). Populated
#: from the auth-code flow's bundle when the platform is Instagram.
SECRET_IG_USER_ID = "ig_user_id"

#: TikTok's refresh-token endpoint (grant_type=refresh_token).
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


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

#: (refresh_token, client_id, client_secret) -> an object with a `.token`
#: attribute (a `google.oauth2.credentials.Credentials` in production).
#: Injectable so tests never touch Google.
YouTubeCredentialsBuilder = Callable[..., Any]

#: (refresh_token, client_id, client_secret) -> the raw token-endpoint JSON
#: (at least `access_token`; TikTok also rotates `refresh_token`). Injectable
#: so tests never touch the network.
TikTokRefreshFlow = Callable[[str, str, str], dict[str, Any]]

#: (platform, bundle) -> True if the credentials are still valid. A minimal,
#: cheap, platform-specific auth probe (YouTube: channels.list mine=true;
#: TikTok: user info; Instagram: /me) — raises on a network/HTTP problem,
#: returns False on a clear auth rejection. Injectable so tests never touch
#: the network/SDKs.
VerifyProbe = Callable[[PublishPlatform, "TokenBundle"], bool]


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
        youtube_credentials_builder: YouTubeCredentialsBuilder | None = None,
        tiktok_refresh_flow: TikTokRefreshFlow | None = None,
        verify_probe: VerifyProbe | None = None,
    ) -> None:
        self._vault = vault
        self._repo = account_repo
        self._youtube_flow = youtube_flow
        self._auth_code_flow = auth_code_flow
        self._youtube_credentials_builder = youtube_credentials_builder
        self._tiktok_refresh_flow = tiktok_refresh_flow
        self._verify_probe = verify_probe

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
        if bundle.get(SECRET_IG_USER_ID):
            ig_key = _key(platform, aid, SECRET_IG_USER_ID)
            await self._vault.set_secret(user_id, ig_key, bundle[SECRET_IG_USER_ID])
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
        """Return the stored token bundle for an account (for upload).

        For platforms with a refresh flow (YouTube, TikTok), eagerly refreshes
        the access token first — a revoked/expired refresh token is caught
        here (account marked EXPIRED) instead of failing opaquely mid-upload.
        """
        aid = str(account.id)
        bundle: TokenBundle = {}
        for secret in (
            SECRET_REFRESH, SECRET_ACCESS, SECRET_CLIENT_ID, SECRET_CLIENT_SECRET, SECRET_IG_USER_ID,
        ):
            val = await self._vault.get_secret(account.user_id, _key(account.platform, aid, secret))
            if val is not None:
                bundle[secret] = val
        if not bundle:
            raise ProviderError(f"{account.platform.value} account not connected")

        if bundle.get(SECRET_REFRESH):
            if account.platform is PublishPlatform.YOUTUBE:
                await self._refresh_youtube_access_token(account, bundle)
            elif account.platform is PublishPlatform.TIKTOK:
                await self._refresh_tiktok_access_token(account, bundle)
        return bundle

    async def verify(self, account: PublishAccount) -> PublishAccount:
        """Health-check an account with one minimal per-platform API call.

        Reuses `credentials()` first so a dead refresh token is already caught
        (and the account marked EXPIRED) before the probe ever runs. The probe
        itself is a cheap read-only call — YouTube: `channels.list(mine=true)`,
        TikTok: user info, Instagram: `/me` — that only proves the access token
        still authenticates; it does not attempt an upload. Returns the
        (possibly updated) account so the caller can surface fresh status.
        """
        try:
            bundle = await self.credentials(account)
        except ProviderError:
            # credentials() already marked EXPIRED on a refresh failure.
            return await self._repo.get(account.id) or account

        probe = self._verify_probe or _default_verify_probe
        try:
            ok = await asyncio.to_thread(probe, account.platform, bundle)
        except Exception as e:
            # Per the VerifyProbe contract, an exception means a NETWORK/HTTP
            # problem (timeout, DNS, 5xx) — not an auth rejection. Leave the
            # account status untouched: marking EXPIRED here would force users
            # to reconnect over a transient outage.
            log.warning(
                "channel.verify_probe_unreachable",
                platform=account.platform.value, account_id=str(account.id), error=str(e),
            )
            return account

        if not ok:
            await self._mark_expired(account)
            return await self._repo.get(account.id) or account
        if account.status is AccountStatus.EXPIRED:
            # Recovered — e.g. the user reconnected out of band.
            restored = account.model_copy(update={
                "status": AccountStatus.CONNECTED, "updated_at": utcnow(),
            })
            await self._repo.save(restored)
            return restored
        return account

    # -- token refresh (token hygiene) ---------------------------------------
    async def _refresh_youtube_access_token(
        self, account: PublishAccount, bundle: TokenBundle,
    ) -> None:
        builder = self._youtube_credentials_builder or build_credentials
        try:
            # builder performs a blocking OAuth network call (creds.refresh) —
            # run it in a worker thread so the event loop stays responsive.
            creds = await asyncio.to_thread(
                builder,
                refresh_token=bundle[SECRET_REFRESH],
                client_id=bundle.get(SECRET_CLIENT_ID, ""),
                client_secret=bundle.get(SECRET_CLIENT_SECRET, ""),
            )
            token = getattr(creds, "token", None)
            if not token:
                raise ProviderError("YouTube refresh returned no access token")
        except Exception as e:
            await self._mark_expired(account)
            raise ProviderError(
                f"YouTube token refresh failed — reconnect the account: {e}"
            ) from e
        bundle[SECRET_ACCESS] = token
        await self._vault.set_secret(
            account.user_id, _key(account.platform, str(account.id), SECRET_ACCESS), token,
        )

    async def _refresh_tiktok_access_token(
        self, account: PublishAccount, bundle: TokenBundle,
    ) -> None:
        try:
            # The refresh flow does a blocking httpx.post — off the event loop.
            fields = await asyncio.to_thread(
                self._run_tiktok_refresh,
                bundle[SECRET_REFRESH],
                bundle.get(SECRET_CLIENT_ID, ""),
                bundle.get(SECRET_CLIENT_SECRET, ""),
            )
            access = fields.get("access_token")
            if not access:
                raise ProviderError("TikTok refresh returned no access token")
        except Exception as e:
            await self._mark_expired(account)
            raise ProviderError(
                f"TikTok token refresh failed — reconnect the account: {e}"
            ) from e
        bundle[SECRET_ACCESS] = access
        aid = str(account.id)
        await self._vault.set_secret(
            account.user_id, _key(account.platform, aid, SECRET_ACCESS), access,
        )
        # TikTok rotates the refresh token on every use — persist it too, or
        # the *next* refresh will fail with a stale token.
        new_refresh = fields.get("refresh_token")
        if new_refresh:
            bundle[SECRET_REFRESH] = new_refresh
            await self._vault.set_secret(
                account.user_id, _key(account.platform, aid, SECRET_REFRESH), new_refresh,
            )

    def _run_tiktok_refresh(
        self, refresh_token: str, client_id: str, client_secret: str,
    ) -> dict[str, Any]:
        if self._tiktok_refresh_flow is not None:
            return self._tiktok_refresh_flow(refresh_token, client_id, client_secret)
        return _default_tiktok_refresh(refresh_token, client_id, client_secret)

    async def _mark_expired(self, account: PublishAccount) -> None:
        if account.status is AccountStatus.EXPIRED:
            return
        expired = account.model_copy(update={
            "status": AccountStatus.EXPIRED, "updated_at": utcnow(),
        })
        await self._repo.save(expired)
        log.warning(
            "channel.token_expired",
            platform=account.platform.value, account_id=str(account.id),
        )

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


def _default_tiktok_refresh(  # pragma: no cover - network, exercised via injected fake
    refresh_token: str, client_id: str, client_secret: str,
) -> dict[str, Any]:
    """POST the refresh_token grant to TikTok's token endpoint.

    https://developers.tiktok.com/doc/oauth-user-access-token-management
    """
    import httpx  # lazy

    resp = httpx.post(TIKTOK_TOKEN_URL, data={
        "client_key": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _default_verify_probe(  # pragma: no cover - network, exercised via injected fake
    platform: PublishPlatform, bundle: TokenBundle,
) -> bool:
    """Minimal read-only auth check per platform. Raises on network errors
    (caller treats that as inconclusive -> False); returns False on a clear
    401/403 rejection, True otherwise."""
    import httpx  # lazy

    access = bundle.get(SECRET_ACCESS)
    if not access:
        return False

    if platform is PublishPlatform.YOUTUBE:
        try:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]
            from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderError("google-api-python-client not installed") from e
        creds = Credentials(token=access)
        service = build("youtube", "v3", credentials=creds)
        resp = service.channels().list(part="id", mine=True).execute()
        return bool(resp.get("items"))

    if platform is PublishPlatform.TIKTOK:
        resp = httpx.post(
            "https://open.tiktokapis.com/v2/user/info/",
            headers={"Authorization": f"Bearer {access}"},
            params={"fields": "open_id"},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()
        return "data" in resp.json()

    if platform is PublishPlatform.INSTAGRAM:
        resp = httpx.get(
            "https://graph.facebook.com/v19.0/me",
            params={"fields": "id", "access_token": access},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()
        return "id" in resp.json()

    return False


__all__ = [
    "OAuthAccountService",
    "PlatformOAuth",
    "PLATFORM_OAUTH",
    "SECRET_ACCESS",
    "SECRET_CLIENT_ID",
    "SECRET_CLIENT_SECRET",
    "SECRET_IG_USER_ID",
    "SECRET_REFRESH",
    "TIKTOK_TOKEN_URL",
    "VerifyProbe",
]
