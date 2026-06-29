"""Per-platform upload dispatch for the Channels Hub.

Given a connected account's token bundle + a video file + metadata, upload to
the right platform and return an ``UploadResult``. YouTube reuses the proven
``YouTubePublisher``. TikTok / Instagram implement the real Content Posting /
Graph upload shapes but are lazy and fail cleanly until the user supplies an
approved app — the rest of the app never breaks if they are not configured.

The platform uploader callables are injectable so tests never hit the network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from videocreator.domain.value_objects import PublishPlatform
from videocreator.infrastructure.publish.channel_accounts import (
    SECRET_ACCESS,
    SECRET_CLIENT_ID,
    SECRET_CLIENT_SECRET,
    SECRET_REFRESH,
)
from videocreator.infrastructure.publish.youtube_publisher import (
    UploadResult,
    YouTubePublisher,
    build_credentials,
)
from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: (path, bundle, metadata) -> UploadResult
PlatformUploader = Callable[[Path, dict[str, Any], dict[str, Any]], UploadResult]


class ChannelPublisher:
    """Dispatches an upload to the correct platform implementation."""

    def __init__(self, uploaders: dict[PublishPlatform, PlatformUploader] | None = None) -> None:
        # Injection point for tests / alternate backends.
        self._uploaders = uploaders or {}

    def upload(
        self,
        platform: PublishPlatform,
        path: Path,
        bundle: dict[str, Any],
        metadata: dict[str, Any],
    ) -> UploadResult:
        if not path.exists():
            raise FileNotFoundError(str(path))
        uploader = self._uploaders.get(platform) or _DEFAULT_UPLOADERS[platform]
        return uploader(path, bundle, metadata)


def _upload_youtube(path: Path, bundle: dict[str, Any], metadata: dict[str, Any]) -> UploadResult:
    refresh = bundle.get(SECRET_REFRESH)
    client_id = bundle.get(SECRET_CLIENT_ID)
    client_secret = bundle.get(SECRET_CLIENT_SECRET)
    if not (refresh and client_id and client_secret):
        raise ProviderError("YouTube account missing credentials — reconnect it")
    creds = build_credentials(
        refresh_token=refresh, client_id=client_id, client_secret=client_secret,
    )
    publisher = YouTubePublisher(creds)
    return publisher.upload(
        path,
        title=str(metadata.get("title") or path.stem),
        description=str(metadata.get("description", "")),
        tags=tuple(metadata.get("tags") or ()),
        privacy=str(metadata.get("privacy", "private")),
        made_for_kids=bool(metadata.get("made_for_kids", False)),
    )


def _upload_tiktok(path: Path, bundle: dict[str, Any], metadata: dict[str, Any]) -> UploadResult:  # pragma: no cover - network
    """TikTok Content Posting API (FILE_UPLOAD). Needs an approved app."""
    access = bundle.get(SECRET_ACCESS)
    if not access:
        raise ProviderError(
            "TikTok account not fully connected — reconnect with an approved app"
        )
    import httpx

    size = path.stat().st_size
    init = httpx.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
        json={
            "post_info": {
                "title": str(metadata.get("title") or path.stem),
                "privacy_level": metadata.get("privacy", "SELF_ONLY"),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
        },
        timeout=60,
    )
    init.raise_for_status()
    data = init.json()["data"]
    upload_url = data["upload_url"]
    publish_id = data["publish_id"]
    with path.open("rb") as fh:
        httpx.put(
            upload_url,
            content=fh.read(),
            headers={
                "Content-Range": f"bytes 0-{size - 1}/{size}",
                "Content-Type": "video/mp4",
            },
            timeout=600,
        ).raise_for_status()
    log.info("tiktok.upload.done", publish_id=publish_id)
    return UploadResult(video_id=publish_id, url="https://www.tiktok.com/")


def _upload_instagram(path: Path, bundle: dict[str, Any], metadata: dict[str, Any]) -> UploadResult:  # pragma: no cover - network
    """Instagram Graph API Reels publish. Needs a Business account + approved app.

    The Graph flow requires a publicly reachable video URL (container → publish).
    Local files are not directly uploadable, so this surfaces a clear error
    pointing at the (future) hosted-URL path rather than silently failing.
    """
    access = bundle.get(SECRET_ACCESS)
    if not access:
        raise ProviderError(
            "Instagram account not fully connected — reconnect with an approved app"
        )
    raise ProviderError(
        "Instagram Reels publishing needs a public video URL (Graph container "
        "flow). Connect storage that serves a public URL to enable it."
    )


_DEFAULT_UPLOADERS: dict[PublishPlatform, PlatformUploader] = {
    PublishPlatform.YOUTUBE: _upload_youtube,
    PublishPlatform.TIKTOK: _upload_tiktok,
    PublishPlatform.INSTAGRAM: _upload_instagram,
}


__all__ = ["ChannelPublisher", "PlatformUploader", "UploadResult"]
