"""Brain endpoints — video analysis, trend radar, scene recreation."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.domain.services.provider_hints import hint_for
from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    AnalyzeVideoRequest,
    FairUseResponse,
    GenomeBeatResponse,
    GenomeHookResponse,
    PlanRecreationRequest,
    RecreationBeatResponse,
    RecreationPlanResponse,
    SceneCandidateResponse,
    SceneTrendMatchRequest,
    ViralGenomeResponse,
)

router = APIRouter(prefix="/brain", tags=["brain"])


@router.post(
    "/analyze",
    response_model=ViralGenomeResponse,
    summary="Analyze a video and extract its viral genome",
)
async def analyze_video(
    body: AnalyzeVideoRequest,
    uc: UseCasesDep,
    user_id: UserIdDep,
) -> ViralGenomeResponse:
    context = body.context or body.url or ""
    genome = await uc.brain.analyze_video.execute(context=context)
    return ViralGenomeResponse(
        format_id=genome.format_id,
        hook=GenomeHookResponse(
            type=genome.hook.type,
            duration_s=genome.hook.duration_s,
            text_overlay=genome.hook.text_overlay,
        ),
        structure=[
            GenomeBeatResponse(
                beat=b.beat,
                duration_s=b.duration_s,
                audio=b.audio,
                camera=b.camera,
                sfx=b.sfx,
                cut_style=b.cut_style,
                visual_description=b.visual_description,
            )
            for b in genome.structure
        ],
        why_it_works=genome.why_it_works,
        remixability=genome.remixability,
        decay_estimate=genome.decay_estimate,
    )


@router.post(
    "/recreations/plan",
    response_model=RecreationPlanResponse,
    summary="Plan a famous-scene recreation (V2V) with fair-use assessment",
)
async def plan_recreation(
    body: PlanRecreationRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> RecreationPlanResponse:
    plan = await uc.brain.plan_recreation.execute(
        original=body.original, niche=body.niche, twist=body.twist,
    )
    hint = hint_for("scene_recreation")
    return RecreationPlanResponse(
        title=plan.title,
        v2v_prompt=plan.v2v_prompt,
        reference_description=plan.reference_description,
        beats=[RecreationBeatResponse(
            beat=b.beat, duration_s=b.duration_s, description=b.description,
        ) for b in plan.beats],
        audio_note=plan.audio_note,
        fair_use=FairUseResponse(
            closeness=plan.fair_use.closeness,
            transformative=plan.fair_use.transformative,
            risk=plan.fair_use.risk,
            guidance=plan.fair_use.guidance,
            requires_confirmation=plan.fair_use.requires_confirmation,
        ),
        provider_hint=list(hint.priorities) if hint else [],
    )


@router.post(
    "/recreations/trend-match",
    response_model=list[SceneCandidateResponse],
    summary="Match trend terms to famous scenes worth recreating",
)
async def scene_trend_match(
    body: SceneTrendMatchRequest,
    uc: UseCasesDep,
    container: ContainerDep,
    user_id: UserIdDep,
) -> list[SceneCandidateResponse]:
    terms = body.terms
    if not terms:
        terms = await container.trend_source().fetch(limit=15)
    candidates = await uc.brain.scene_trend_match.execute(terms)
    return [SceneCandidateResponse(
        term=c.term, scene=c.scene, why_trending=c.why_trending,
    ) for c in candidates]


__all__ = ["router"]
