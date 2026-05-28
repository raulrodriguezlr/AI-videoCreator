"""Episode endpoints — create from a script + enqueue heavy rendering."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CreateEpisodeRequest,
    EnqueueRenderResponse,
    EpisodeResponse,
)
from videocreator.shared.ids import EpisodeId, PodId, ScriptId

router = APIRouter(prefix="/pods/{pod_id}/episodes", tags=["episodes"])


def _to_response(ep) -> EpisodeResponse:  # type: ignore[no-untyped-def]
    return EpisodeResponse(
        id=ep.id, pod_id=ep.pod_id, topic_id=ep.topic_id, script_id=ep.script_id,
        title=ep.title, number=ep.number, state=ep.state,
        final_video_key=ep.final_video_key, dubbed_video_key=ep.dubbed_video_key,
        youtube_video_id=ep.youtube_video_id,
        created_at=ep.created_at, updated_at=ep.updated_at,
    )


@router.get("", response_model=list[EpisodeResponse], summary="List pod episodes")
async def list_episodes(
    pod_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> list[EpisodeResponse]:
    eps = await uc.episodes.list.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return [_to_response(e) for e in eps]


@router.post(
    "", response_model=EpisodeResponse, status_code=status.HTTP_201_CREATED,
    summary="Create an episode from a script (no render yet)",
)
async def create_episode(
    pod_id: str, body: CreateEpisodeRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> EpisodeResponse:
    ep = await uc.episodes.create_from_script.execute(
        pod_id=PodId(pod_id), script_id=ScriptId(body.script_id),
        requester_id=user_id, title=body.title,
    )
    return _to_response(ep)


@router.get(
    "/{episode_id}", response_model=EpisodeResponse, summary="Get an episode",
)
async def get_episode(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EpisodeResponse:
    del pod_id
    ep = await uc.episodes.get.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    return _to_response(ep)


@router.post(
    "/{episode_id}/render", response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue full video rendering for the episode",
)
async def enqueue_render(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EnqueueRenderResponse:
    del pod_id
    job_id = await uc.episodes.enqueue_render.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    return EnqueueRenderResponse(job_id=job_id)


__all__ = ["router"]
