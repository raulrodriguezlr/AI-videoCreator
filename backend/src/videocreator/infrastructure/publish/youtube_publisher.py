"""YouTube upload + analytics — the only platform with a stable upload API.

OAuth2 flow runs once out-of-band; the refresh token lives in the vault.
google-api-python-client is a lazy import: without it the publisher raises a
clear ProviderError instead of breaking module import (local-first).

TikTok Content Posting / Instagram Graph need app review — phase 2; until
then the flow is export + reminder.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_PRIVACY_STATUSES = ("private", "unlisted", "public")
_MAX_TITLE_LEN = 100


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    url: str


class YouTubePublisher:
    """Resumable upload + analytics queries against YouTube Data/Analytics v3.

    `service_factory` / `analytics_factory` exist for testability and DI:
    production passes None and the googleapiclient services are built lazily
    from `credentials`.
    """

    def __init__(
        self,
        credentials: Any = None,
        *,
        service_factory: Callable[[], Any] | None = None,
        analytics_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._credentials = credentials
        self._service_factory = service_factory
        self._analytics_factory = analytics_factory

    def upload(
        self,
        path: Path,
        *,
        title: str,
        description: str = "",
        tags: tuple[str, ...] = (),
        privacy: str = "private",
        made_for_kids: bool = False,
    ) -> UploadResult:
        """Upload a video file. Defaults to private per §16.14."""
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not title.strip():
            raise ValueError("title must not be empty")
        if len(title) > _MAX_TITLE_LEN:
            raise ValueError(f"title exceeds {_MAX_TITLE_LEN} characters")
        if privacy not in _PRIVACY_STATUSES:
            raise ValueError(f"privacy must be one of {_PRIVACY_STATUSES}")

        service = self._service()
        media = self._media_upload(path)
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": list(tags),
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        try:
            response = service.videos().insert(
                part="snippet,status", body=body, media_body=media,
            ).execute()
        except Exception as e:
            log.error("youtube.upload.failed", error=str(e))
            raise ProviderError(f"YouTube upload failed: {e}") from e

        video_id = response["id"]
        log.info("youtube.upload.done", video_id=video_id, privacy=privacy)
        return UploadResult(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    def query_metrics(
        self,
        *,
        start_date: str,
        end_date: str,
        video_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """YouTube Analytics query per §16.14. Returns raw row dicts."""
        analytics = self._analytics()
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "views,averageViewPercentage,audienceWatchRatio",
            "dimensions": "video,day",
        }
        if video_ids:
            params["filters"] = "video==" + ",".join(video_ids)
        try:
            response = analytics.reports().query(**params).execute()
        except Exception as e:
            log.error("youtube.analytics.failed", error=str(e))
            raise ProviderError(f"YouTube Analytics query failed: {e}") from e

        headers = [h["name"] for h in response.get("columnHeaders", [])]
        return [dict(zip(headers, row)) for row in response.get("rows", [])]

    def _service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        build = self._import_build()
        return build("youtube", "v3", credentials=self._credentials)

    def _analytics(self) -> Any:
        if self._analytics_factory is not None:
            return self._analytics_factory()
        build = self._import_build()
        return build("youtubeAnalytics", "v2", credentials=self._credentials)

    @staticmethod
    def _import_build() -> Any:
        try:
            from googleapiclient.discovery import build  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderError(
                "google-api-python-client not installed — "
                "pip install google-api-python-client google-auth-oauthlib"
            ) from e
        return build

    @staticmethod
    def _media_upload(path: Path) -> Any:
        try:
            from googleapiclient.http import MediaFileUpload  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderError("google-api-python-client not installed") from e
        return MediaFileUpload(str(path), resumable=True)


def build_credentials(
    *, refresh_token: str, client_id: str, client_secret: str,
) -> Any:
    """Rebuild OAuth2 Credentials from a stored refresh token (vault).

    Eagerly refreshes the access token on construction (token hygiene): a
    revoked/expired refresh token then surfaces here as a clear ProviderError
    instead of failing deep inside a googleapiclient upload call. Callers that
    persist tokens (e.g. `OAuthAccountService.credentials`) should read the
    fresh `.token` off the returned Credentials and store it.
    """
    try:
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]
        from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
    except ImportError as e:
        raise ProviderError("google-auth not installed") from e
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    try:
        creds.refresh(Request())
    except Exception as e:
        log.error("youtube.token_refresh.failed", error=str(e))
        raise ProviderError(f"YouTube token refresh failed: {e}") from e
    return creds


__all__ = ["UploadResult", "YouTubePublisher", "build_credentials"]
