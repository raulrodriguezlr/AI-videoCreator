"""Short endpoints — derive a vertical short from an episode + enqueue rendering."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CreateShortRequest,
    EnqueueRenderResponse,
    GenerateNativeShortRequest,
    NativeShortStructureResponse,
    ShortResponse,
    ShortSegmentResponse,
)
from videocreator.shared.ids import EpisodeId, PodId, ShortId

router = APIRouter(prefix="/pods/{pod_id}/shorts", tags=["shorts"])


def _to_response(s) -> ShortResponse:  # type: ignore[no-untyped-def]
    return ShortResponse(
        id=s.id, pod_id=s.pod_id, source_episode_id=s.source_episode_id,
        aspect=s.aspect, duration_s=s.duration_s, hook_text=s.hook_text,
        rendered_video_key=s.rendered_video_key, target_platform=s.target_platform,
        created_at=s.created_at,
    )


@router.get("", response_model=list[ShortResponse], summary="List pod shorts")
async def list_shorts(
    pod_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> list[ShortResponse]:
    shorts = await uc.shorts.list.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return [_to_response(s) for s in shorts]


@router.post(
    "", response_model=ShortResponse, status_code=status.HTTP_201_CREATED,
    summary="Create a short from an episode (no render yet)",
)
async def create_short(
    pod_id: str, body: CreateShortRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> ShortResponse:
    short = await uc.shorts.create_from_episode.execute(
        pod_id=PodId(pod_id),
        source_episode_id=EpisodeId(body.source_episode_id),
        requester_id=user_id,
        duration_s=body.duration_s,
        target_platform=body.target_platform,
        hook_text=body.hook_text,
    )
    return _to_response(short)


@router.get(
    "/{short_id}", response_model=ShortResponse, summary="Get a short",
)
async def get_short(
    pod_id: str, short_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> ShortResponse:
    del pod_id
    short = await uc.shorts.get.execute(short_id=ShortId(short_id), requester_id=user_id)
    return _to_response(short)


@router.post(
    "/{short_id}/render", response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue vertical reframe/render for the short",
)
async def enqueue_render(
    pod_id: str, short_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EnqueueRenderResponse:
    del pod_id
    job_id = await uc.shorts.enqueue_render.execute(
        short_id=ShortId(short_id), requester_id=user_id,
    )
    return EnqueueRenderResponse(job_id=job_id)


@router.post(
    "/native",
    response_model=NativeShortStructureResponse,
    summary="Generate native short-form structure from concept via LLM",
)
async def generate_native_short(
    pod_id: str,
    body: GenerateNativeShortRequest,
    uc: UseCasesDep,
    user_id: UserIdDep,
) -> NativeShortStructureResponse:
    del pod_id, user_id
    structure = await uc.shorts.generate_native.execute(
        concept=body.concept,
        content_type=body.content_type,
        duration_s=body.duration_s,
    )
    return NativeShortStructureResponse(
        total_duration_s=structure.total_duration_s,
        segments=[
            ShortSegmentResponse(
                role=seg.role,
                duration_s=seg.duration_s,
                visual_prompt=seg.visual_prompt,
                audio_text=seg.audio_text,
                sfx_vibe=seg.sfx_vibe,
                cut_style=seg.cut_style,
            )
            for seg in structure.segments
        ],
        music_vibe=structure.music_vibe,
        caption_keywords=list(structure.caption_keywords),
    )


__all__ = ["router"]
