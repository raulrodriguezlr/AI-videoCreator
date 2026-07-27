"""SEO endpoints — generate publishing metadata and optimize the title.

Nested under an episode: a video's SEO is derived from it. `recommend` and
`feedback` drive the LinUCB title bandit (pick best variant / learn from
observed engagement).
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.domain.entities import SeoMetadata
from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    GenerateSeoRequest,
    RecommendTitleResponse,
    RecordTitleOutcomeRequest,
    SeoMetadataResponse,
)
from videocreator.shared.ids import EpisodeId, PodId

router = APIRouter(prefix="/pods/{pod_id}/episodes/{episode_id}/seo", tags=["seo"])


def _to_response(seo: SeoMetadata) -> SeoMetadataResponse:
    return SeoMetadataResponse(
        id=seo.id,
        pod_id=seo.pod_id,
        episode_id=seo.episode_id,
        description=seo.description,
        tags=seo.tags,
        hashtags=seo.hashtags,
        title_variants=seo.title_variants,
        selected_title=seo.selected_title,
        created_at=seo.created_at,
        updated_at=seo.updated_at,
    )


@router.post(
    "",
    response_model=SeoMetadataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate SEO metadata + seed the title bandit",
)
async def generate_seo(
    pod_id: str,
    episode_id: str,
    body: GenerateSeoRequest,
    uc: UseCasesDep,
    user_id: UserIdDep,
) -> SeoMetadataResponse:
    seo = await uc.seo.generate.execute(
        pod_id=PodId(pod_id),
        episode_id=EpisodeId(episode_id),
        requester_id=user_id,
        variant_count=body.variant_count,
    )
    return _to_response(seo)


@router.get("", response_model=SeoMetadataResponse, summary="Get an episode's SEO metadata")
async def get_seo(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> SeoMetadataResponse:
    del pod_id
    seo = await uc.seo.get.execute(episode_id=EpisodeId(episode_id), requester_id=user_id)
    return _to_response(seo)


@router.post(
    "/recommend",
    response_model=RecommendTitleResponse,
    summary="Recommend the best title variant (LinUCB)",
)
async def recommend_title(
    pod_id: str, episode_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> RecommendTitleResponse:
    del pod_id
    decision = await uc.seo.recommend.execute(
        episode_id=EpisodeId(episode_id), requester_id=user_id,
    )
    return RecommendTitleResponse(
        title=decision.arm_id, score=decision.score, scores=decision.scores,
    )


@router.post(
    "/feedback",
    response_model=SeoMetadataResponse,
    summary="Record a title's observed reward (updates the bandit)",
)
async def record_outcome(
    pod_id: str,
    episode_id: str,
    body: RecordTitleOutcomeRequest,
    uc: UseCasesDep,
    user_id: UserIdDep,
) -> SeoMetadataResponse:
    del pod_id
    seo = await uc.seo.record_outcome.execute(
        episode_id=EpisodeId(episode_id),
        requester_id=user_id,
        title=body.title,
        reward=body.reward,
    )
    return _to_response(seo)


__all__ = ["router"]
