"""Brain endpoints — video analysis, trend radar, daily briefing."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    AnalyzeVideoRequest,
    GenomeBeatResponse,
    GenomeHookResponse,
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


__all__ = ["router"]
