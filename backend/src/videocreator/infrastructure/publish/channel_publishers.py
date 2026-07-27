"""Per-platform upload dispatch for the Channels Hub.

Given a connected account's token bundle + a video file + metadata, upload to
the right platform and return an ``UploadResult``. YouTube reuses the proven
``YouTubePublisher``. TikTok implements the real Content Posting API upload +
status-poll (FILE_UPLOAD init -> PUT bytes -> poll publish status until it
settles). Instagram implements the real Graph container -> publish flow, but
needs a publicly reachable video URL (``PUBLIC_MEDIA_BASE_URL``) — without it,
``PublishService.enqueue`` rejects Instagram jobs before they ever reach here.

The platform uploader callables are injectable so tests never hit the network.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from videocreator.domain.value_objects import PublishPlatform
from videocreator.infrastructure.publish.channel_accounts import (
    SECRET_ACCESS,
    SECRET_CLIENT_ID,
    SECRET_CLIENT_SECRET,
    SECRET_IG_USER_ID,
    SECRET_REFRESH,
)
from videocreator.infrastructure.publish.youtube_publisher import (
    UploadResult,
    YouTubePublisher,
    build_credentials,
)
from videocreator.shared.errors import ProviderError, ProviderTimeoutError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: (path, bundle, metadata) -> UploadResult
PlatformUploader = Callable[[Path, dict[str, Any], dict[str, Any]], UploadResult]

#: TikTok's publish-status polling endpoint (body: {"publish_id": ...}).
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

#: Polling budget: ~5 minutes, starting at 5s and backing off to 15s.
TIKTOK_POLL_TIMEOUT_S = 300.0
TIKTOK_POLL_START_INTERVAL_S = 5.0
TIKTOK_POLL_MAX_INTERVAL_S = 15.0

#: (access_token, publish_id) -> raw status-endpoint JSON. Injectable for tests.
TikTokStatusPoller = Callable[[str, str], dict[str, Any]]

#: Instagram Graph API base (container create + status + publish).
IG_GRAPH_BASE = "https://graph.facebook.com/v19.0"

#: Polling budget for the Graph media-container status (video processing).
IG_POLL_TIMEOUT_S = 300.0
IG_POLL_START_INTERVAL_S = 5.0
IG_POLL_MAX_INTERVAL_S = 15.0

#: (access_token, container_id) -> raw container status-check JSON. Injectable.
InstagramContainerPoller = Callable[[str, str], dict[str, Any]]


class ChannelPublisher:
    """Dispatches an upload to the correct platform implementation."""

    def __init__(
        self,
        uploaders: dict[PublishPlatform, PlatformUploader] | None = None,
        *,
        tiktok_status_poller: TikTokStatusPoller | None = None,
        instagram_container_poller: InstagramContainerPoller | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        # Injection point for tests / alternate backends.
        self._uploaders = uploaders or {}
        self._tiktok_status_poller = tiktok_status_poller
        self._instagram_container_poller = instagram_container_poller
        self._sleep = sleep or time.sleep

    def upload(
        self,
        platform: PublishPlatform,
        path: Path,
        bundle: dict[str, Any],
        metadata: dict[str, Any],
    ) -> UploadResult:
        if not path.exists():
            raise FileNotFoundError(str(path))
        uploader = self._uploaders.get(platform)
        if uploader is not None:
            return uploader(path, bundle, metadata)
        if platform is PublishPlatform.TIKTOK:
            return _upload_tiktok(
                path, bundle, metadata,
                status_poller=self._tiktok_status_poller, sleep=self._sleep,
            )
        if platform is PublishPlatform.INSTAGRAM:
            return _upload_instagram(
                path, bundle, metadata,
                container_poller=self._instagram_container_poller, sleep=self._sleep,
            )
        return _DEFAULT_UPLOADERS[platform](path, bundle, metadata)


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


def _default_tiktok_status_poll(  # pragma: no cover - network
    access_token: str, publish_id: str
) -> dict[str, Any]:
    """POST the publish_id to TikTok's status-fetch endpoint; returns raw JSON."""
    import httpx  # lazy

    resp = httpx.post(
        TIKTOK_STATUS_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"publish_id": publish_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_tiktok_publish_status(
    access_token: str,
    publish_id: str,
    *,
    status_poller: TikTokStatusPoller | None,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    """Poll until PUBLISH_COMPLETE / FAILED / timeout (5 min, 5s->15s backoff)."""
    poller = status_poller or _default_tiktok_status_poll
    deadline = time.monotonic() + TIKTOK_POLL_TIMEOUT_S
    interval = TIKTOK_POLL_START_INTERVAL_S
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        raw = poller(access_token, publish_id)
        last = raw.get("data", raw)
        status = last.get("status")
        if status == "PUBLISH_COMPLETE":
            return last
        if status == "FAILED":
            reason = last.get("fail_reason") or last.get("error") or "unknown reason"
            raise ProviderError(f"TikTok publish failed: {reason}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep(min(interval, remaining))
        interval = min(interval * 1.5, TIKTOK_POLL_MAX_INTERVAL_S)
    raise ProviderTimeoutError(
        f"TikTok publish status did not settle within {int(TIKTOK_POLL_TIMEOUT_S)}s "
        f"(publish_id={publish_id}, last status={last.get('status')!r})"
    )


def _upload_tiktok(
    path: Path,
    bundle: dict[str, Any],
    metadata: dict[str, Any],
    *,
    status_poller: TikTokStatusPoller | None = None,
    sleep: Callable[[float], None] | None = None,
) -> UploadResult:  # pragma: no cover - network
    """TikTok Content Posting API (FILE_UPLOAD) + status poll to completion."""
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
    log.info("tiktok.upload.uploaded", publish_id=publish_id)

    status = _poll_tiktok_publish_status(
        access, publish_id, status_poller=status_poller, sleep=sleep or time.sleep,
    )
    video_id = str(
        status.get("publicaly_available_post_id") or status.get("publish_id") or publish_id
    )
    # TikTok's status payload doesn't reliably include a share URL for
    # FILE_UPLOAD posts; fall back to the generic app URL if none is given.
    url = status.get("share_url") or "https://www.tiktok.com/"
    log.info("tiktok.upload.done", publish_id=publish_id, status=status.get("status"))
    return UploadResult(video_id=video_id, url=url)


def _default_instagram_container_poll(  # pragma: no cover - network
    access_token: str, container_id: str
) -> dict[str, Any]:
    """GET the container's `status_code` (Graph media-container status check)."""
    import httpx  # lazy

    resp = httpx.get(
        f"{IG_GRAPH_BASE}/{container_id}",
        params={"fields": "status_code", "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_instagram_container(
    access_token: str,
    container_id: str,
    *,
    container_poller: InstagramContainerPoller | None,
    sleep: Callable[[float], None],
) -> None:
    """Poll a Graph media container until it's FINISHED (or ERROR/timeout)."""
    poller = container_poller or _default_instagram_container_poll
    deadline = time.monotonic() + IG_POLL_TIMEOUT_S
    interval = IG_POLL_START_INTERVAL_S
    last_status = None
    while time.monotonic() < deadline:
        data = poller(access_token, container_id)
        last_status = data.get("status_code")
        if last_status == "FINISHED":
            return
        if last_status == "ERROR":
            raise ProviderError(
                f"Instagram media container failed processing: {data}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep(min(interval, remaining))
        interval = min(interval * 1.5, IG_POLL_MAX_INTERVAL_S)
    raise ProviderTimeoutError(
        f"Instagram media container did not finish within {int(IG_POLL_TIMEOUT_S)}s "
        f"(container_id={container_id}, last status={last_status!r})"
    )


def _upload_instagram(
    path: Path,
    bundle: dict[str, Any],
    metadata: dict[str, Any],
    *,
    container_poller: InstagramContainerPoller | None = None,
    sleep: Callable[[float], None] | None = None,
) -> UploadResult:  # pragma: no cover - network
    """Instagram Graph API Reels publish: container -> poll -> media_publish.

    The Graph flow only accepts a publicly reachable ``video_url`` — never an
    uploaded file — so ``PublishService`` builds one from
    ``PUBLIC_MEDIA_BASE_URL`` and passes it in ``metadata["public_video_url"]``
    before calling this. `PublishService.enqueue` rejects Instagram jobs before
    they ever reach here when that setting is absent, so a missing URL at this
    point is treated as a programming error, not a user-facing one.
    """
    access = bundle.get(SECRET_ACCESS)
    if not access:
        raise ProviderError(
            "Instagram account not fully connected — reconnect with an approved app"
        )
    ig_user_id = bundle.get(SECRET_IG_USER_ID)
    if not ig_user_id:
        raise ProviderError(
            "Instagram account is missing its Business account id — reconnect it"
        )
    video_url = metadata.get("public_video_url")
    if not video_url:
        raise ProviderError(
            "Instagram upload requires metadata['public_video_url'] — "
            "configure PUBLIC_MEDIA_BASE_URL in Settings and retry"
        )

    import httpx  # lazy

    create = httpx.post(
        f"{IG_GRAPH_BASE}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": str(metadata.get("title") or metadata.get("description") or ""),
            "access_token": access,
        },
        timeout=60,
    )
    create.raise_for_status()
    container_id = create.json()["id"]
    log.info("instagram.container.created", container_id=container_id)

    _poll_instagram_container(
        access, container_id, container_poller=container_poller, sleep=sleep or time.sleep,
    )

    publish = httpx.post(
        f"{IG_GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": access},
        timeout=60,
    )
    publish.raise_for_status()
    media_id = publish.json()["id"]
    log.info("instagram.upload.done", media_id=media_id)
    return UploadResult(video_id=media_id, url=f"https://www.instagram.com/reel/{media_id}/")


_DEFAULT_UPLOADERS: dict[PublishPlatform, PlatformUploader] = {
    PublishPlatform.YOUTUBE: _upload_youtube,
    PublishPlatform.TIKTOK: _upload_tiktok,
    PublishPlatform.INSTAGRAM: _upload_instagram,
}


__all__ = ["ChannelPublisher", "PlatformUploader", "UploadResult"]
