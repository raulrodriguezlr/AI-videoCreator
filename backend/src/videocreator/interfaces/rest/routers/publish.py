"""Publishing endpoints — YouTube OAuth lifecycle + upload (§16.14).

POST /publish/youtube/connect runs the one-time local consent flow (opens a
browser on the machine running the backend — local-first desktop flow); the
refresh token lands in the vault and uploads work unattended afterwards.

POST /publish/youtube/upload uploads a finished episode to YouTube using
the stored credentials.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    ConnectYouTubeRequest,
    YouTubeStatusResponse,
    YouTubeUploadRequest,
    YouTubeUploadResponse,
)
from videocreator.shared.errors import NotFoundError, ProviderError, ValidationError
from videocreator.shared.ids import EpisodeId

router = APIRouter(prefix="/publish", tags=["publish"])


@router.get(
    "/youtube",
    response_model=YouTubeStatusResponse,
    summary="YouTube connection status",
)
async def youtube_status(
    container: ContainerDep, user_id: UserIdDep,
) -> YouTubeStatusResponse:
    result = await container.youtube_oauth().status(user_id)
    return YouTubeStatusResponse(connected=result.connected)


@router.post(
    "/youtube/connect",
    response_model=YouTubeStatusResponse,
    summary="Run the one-time YouTube OAuth consent flow",
)
async def youtube_connect(
    body: ConnectYouTubeRequest, container: ContainerDep, user_id: UserIdDep,
) -> YouTubeStatusResponse:
    result = await container.youtube_oauth().connect(
        user_id, client_id=body.client_id, client_secret=body.client_secret,
    )
    return YouTubeStatusResponse(connected=result.connected)


@router.post(
    "/youtube/upload",
    response_model=YouTubeUploadResponse,
    summary="Upload a finished episode to YouTube",
)
async def youtube_upload(
    body: YouTubeUploadRequest, container: ContainerDep,
    uc: UseCasesDep, user_id: UserIdDep,
) -> YouTubeUploadResponse:
    from videocreator.infrastructure.media.library import EPISODE_BUCKET
    from videocreator.infrastructure.publish.youtube_publisher import YouTubePublisher

    episode = await uc.episodes.get.execute(
        episode_id=EpisodeId(body.episode_id), requester_id=user_id,
    )
    video_key = episode.dubbed_video_key or episode.final_video_key
    if not video_key:
        raise ValidationError("Episode has no rendered video to upload")

    storage = container.storage()
    video_path: Path = await storage.open_path(EPISODE_BUCKET, video_key)
    if not video_path.exists():
        raise NotFoundError(f"Video file not found: {video_key}")

    credentials = await container.youtube_oauth().build_credentials(user_id)
    publisher = YouTubePublisher(credentials)

    title = body.title or episode.title
    description = body.description or ""
    if not description and (seo := await _get_seo(uc, episode)):
        description = seo.description or ""
    tags = tuple(body.tags)
    if not tags and (seo := await _get_seo(uc, episode)):
        tags = tuple(seo.tags or [])

    result = await asyncio.to_thread(
        publisher.upload,
        video_path,
        title=title,
        description=description,
        tags=tags,
        privacy=body.privacy,
    )

    episode.youtube_video_id = result.video_id
    await container.episode_repo().save(episode)

    return YouTubeUploadResponse(video_id=result.video_id, url=result.url)


@router.delete(
    "/youtube",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect YouTube (drop stored credentials)",
)
async def youtube_disconnect(
    container: ContainerDep, user_id: UserIdDep,
) -> None:
    await container.youtube_oauth().disconnect(user_id)


async def _get_seo(uc: Any, episode: Any) -> Any:
    try:
        return await uc.seo.get.execute(episode_id=episode.id)
    except Exception:
        return None


__all__ = ["router"]
