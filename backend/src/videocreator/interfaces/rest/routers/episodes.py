"""Episode endpoints — CRUD, the workspace aggregate, media listing + render.

Media artifacts (mp4/png/wav/…) live in the object store under
``episodes/<id>/<rel>``; ``/media`` returns their ``/api/v1/storage/...`` URLs
and the bytes are streamed (with HTTP range support) by the storage router.
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.application.use_cases.episodes import EpisodeDetail
from videocreator.domain.entities import Episode
from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CreateEpisodeRequest,
    EnqueueRenderResponse,
    EpisodeDetailResponse,
    EpisodeResponse,
    MediaAssetResponse,
    SceneResponse,
    ScriptResponse,
    SeoMetadataResponse,
    UpdateEpisodeRequest,
)
from videocreator.shared.ids import EpisodeId, PodId, ScriptId

router = APIRouter(prefix="/pods/{pod_id}/episodes", tags=["episodes"])


def _to_response(ep: Episode) -> EpisodeResponse:
    return EpisodeResponse(
        id=ep.id, pod_id=ep.pod_id, topic_id=ep.topic_id, script_id=ep.script_id,
        title=ep.title, number=ep.number, state=ep.state,
        final_video_key=ep.final_video_key, dubbed_video_key=ep.dubbed_video_key,
        youtube_video_id=ep.youtube_video_id,
        video_provider=ep.video_provider, video_model=ep.video_model,
        source="filesystem" if ep.extra.get("media_dir") else "native",
        created_at=ep.created_at, updated_at=ep.updated_at,
    )


def _script_to_response(script) -> ScriptResponse:  # type: ignore[no-untyped-def]
    return ScriptResponse(
        id=script.id, pod_id=script.pod_id, topic_id=script.topic_id,
        version=script.version, title=script.title, summary=script.summary,
        reviewed=script.reviewed, created_at=script.created_at,
        scenes=[
            SceneResponse(
                id=s.id, index=s.index, visual_prompt=s.visual_prompt,
                audio_text=s.audio_text, duration_s=s.duration_s,
                camera_shot=s.camera_shot, camera_movement=s.camera_movement,
                camera_angle=s.camera_angle, transition=s.transition,
            )
            for s in script.scenes
        ],
    )


def _seo_to_response(seo) -> SeoMetadataResponse:  # type: ignore[no-untyped-def]
    return SeoMetadataResponse(
        id=seo.id, pod_id=seo.pod_id, episode_id=seo.episode_id,
        description=seo.description, tags=seo.tags, hashtags=seo.hashtags,
        title_variants=seo.title_variants, selected_title=seo.selected_title,
        created_at=seo.created_at, updated_at=seo.updated_at,
    )


def _detail_to_response(detail: EpisodeDetail) -> EpisodeDetailResponse:
    return EpisodeDetailResponse(
        episode=_to_response(detail.episode),
        script=_script_to_response(detail.script) if detail.script else None,
        seo=_seo_to_response(detail.seo) if detail.seo else None,
        media=[MediaAssetResponse(**m.model_dump()) for m in detail.media],
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


@router.get("/{episode_id}", response_model=EpisodeResponse, summary="Get an episode")
async def get_episode(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EpisodeResponse:
    del pod_id
    ep = await uc.episodes.get.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    return _to_response(ep)


@router.get(
    "/{episode_id}/detail", response_model=EpisodeDetailResponse,
    summary="Episode workspace: episode + script + SEO + media in one call",
)
async def get_episode_detail(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EpisodeDetailResponse:
    del pod_id
    detail = await uc.episodes.detail.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    return _detail_to_response(detail)


@router.patch("/{episode_id}", response_model=EpisodeResponse, summary="Edit an episode")
async def update_episode(
    pod_id: str, episode_id: str, body: UpdateEpisodeRequest,
    uc: UseCasesDep, user_id: UserIdDep,
) -> EpisodeResponse:
    del pod_id
    # Use model_fields_set so an omitted field means "unchanged" while an
    # explicit null clears the per-episode override.
    sent = body.model_fields_set
    kwargs: dict[str, object] = {}
    if "title" in sent:
        kwargs["title"] = body.title
    if "state" in sent:
        kwargs["state"] = body.state
    if "video_provider" in sent:
        kwargs["video_provider"] = body.video_provider
    if "video_model" in sent:
        kwargs["video_model"] = body.video_model
    ep = await uc.episodes.update.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id, **kwargs,
    )
    return _to_response(ep)


@router.delete(
    "/{episode_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an episode",
)
async def delete_episode(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    del pod_id
    await uc.episodes.delete.execute(episode_id=EpisodeId(episode_id), requester_id=user_id)


@router.get(
    "/{episode_id}/media", response_model=list[MediaAssetResponse],
    summary="List every viewable media artifact for the episode",
)
async def list_episode_media(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
    container: ContainerDep,
) -> list[MediaAssetResponse]:
    del pod_id
    episode = await uc.episodes.get.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    assets = await container.media_library().list_for_episode(episode)
    return [MediaAssetResponse(**a.model_dump()) for a in assets]


@router.post(
    "/{episode_id}/render", response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue full video rendering for the episode",
)
async def enqueue_render(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
    resume: bool = False,
) -> EnqueueRenderResponse:
    """Render the episode. `resume=true` continues an interrupted render from the
    last completed scene instead of starting over (clips already on disk are kept,
    and the engine seeds the next scene i2v from the last good frame)."""
    del pod_id
    job_id = await uc.episodes.enqueue_render.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
        extra_payload={"resume": True} if resume else None,
    )
    return EnqueueRenderResponse(job_id=job_id)


@router.post(
    "/{episode_id}/scenes/{index}/regenerate",
    response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Regenerate one scene's clip (keep the rest) and recompile the final",
)
async def regenerate_scene(
    pod_id: str, episode_id: str, index: int, uc: UseCasesDep, user_id: UserIdDep,
) -> EnqueueRenderResponse:
    """Redo only scene `index` of an already-rendered episode (e.g. you don't like
    how it turned out) using the current — possibly edited — prompt, then re-dub
    that scene and recompile the final video. The other clips are kept."""
    del pod_id
    job_id = await uc.episodes.enqueue_render.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
        extra_payload={"regen_scene": index},
    )
    return EnqueueRenderResponse(job_id=job_id)


@router.post(
    "/{episode_id}/scenes/{index}/redub", response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-dub one scene's audio and recompile the final video",
)
async def redub_scene(
    pod_id: str, episode_id: str, index: int, uc: UseCasesDep, user_id: UserIdDep,
) -> EnqueueRenderResponse:
    """Re-run the TTS dubbing for scene `index` (e.g. after changing its voice or
    dialogue) without regenerating the video, then recompile the dubbed final."""
    del pod_id
    job_id = await uc.episodes.enqueue_render.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
        extra_payload={"redub_scene": index},
    )
    return EnqueueRenderResponse(job_id=job_id)


@router.post(
    "/{episode_id}/redub", response_model=EnqueueRenderResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-dub every scene and recompile the dubbed final video",
)
async def redub_all(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> EnqueueRenderResponse:
    """Re-dub all clips (replacing existing dubs) and recompile a single dubbed
    final that replaces the episode's dubbed video."""
    del pod_id
    job_id = await uc.episodes.enqueue_render.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
        extra_payload={"redub_all": True},
    )
    return EnqueueRenderResponse(job_id=job_id)


__all__ = ["router"]
