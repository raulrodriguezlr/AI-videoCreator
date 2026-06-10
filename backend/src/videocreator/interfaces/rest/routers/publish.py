"""Publishing endpoints — YouTube OAuth lifecycle (§16.14).

POST /publish/youtube/connect runs the one-time local consent flow (opens a
browser on the machine running the backend — local-first desktop flow); the
refresh token lands in the vault and uploads work unattended afterwards.
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import ContainerDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    ConnectYouTubeRequest,
    YouTubeStatusResponse,
)

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


@router.delete(
    "/youtube",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect YouTube (drop stored credentials)",
)
async def youtube_disconnect(
    container: ContainerDep, user_id: UserIdDep,
) -> None:
    await container.youtube_oauth().disconnect(user_id)


__all__ = ["router"]
