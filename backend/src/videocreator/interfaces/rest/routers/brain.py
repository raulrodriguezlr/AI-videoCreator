"""Brain endpoints — video analysis, trend radar, scene recreation."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

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
    RecreationResponse,
    RecreationListResponse,
    UpdateRecreationRequest,
    SceneCandidateResponse,
    SceneTrendMatchRequest,
    ViralGenomeResponse,
)
from videocreator.domain.entities import Recreation
from videocreator.domain.value_objects import RecreationState
from videocreator.domain.services.provider_hints import filter_available
from videocreator.shared.ids import new_recreation_id, RecreationId
from fastapi import HTTPException
import asyncio
import uuid

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
    summary="Plan a famous-scene recreation (V2V) with fair-use assessment and save as draft",
)
async def plan_recreation(
    body: PlanRecreationRequest, uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> RecreationPlanResponse:
    plan = await uc.brain.plan_recreation.execute(
        original=body.original, niche=body.niche, twist=body.twist,
    )
    
    hint = hint_for("scene_recreation")
    available_providers = set(await container.secret_vault().list_providers(user_id))
    available_providers |= container.available_provider_names()

    filtered_hint = filter_available(hint, available_providers)

    # Persist as draft
    recreation = Recreation(
        id=new_recreation_id(),
        owner_id=user_id,
        state=RecreationState.DRAFT,
        title=plan.title,
        original=body.original,
        niche=body.niche,
        twist=body.twist,
        v2v_prompt=plan.v2v_prompt,
        beats=[{"beat": b.beat, "duration_s": b.duration_s, "description": b.description} for b in plan.beats],
        audio_note=plan.audio_note,
        reference_description=plan.reference_description,
        fair_use={
            "closeness": plan.fair_use.closeness,
            "transformative": plan.fair_use.transformative,
            "risk": plan.fair_use.risk,
            "guidance": plan.fair_use.guidance,
            "requires_confirmation": plan.fair_use.requires_confirmation,
        },
    )
    await container.recreation_repo().save(recreation)

    return RecreationPlanResponse(
        id=str(recreation.id),
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
        provider_hint=filtered_hint,
    )


@router.get(
    "/recreations",
    response_model=RecreationListResponse,
    summary="List the user's recreation drafts and history",
)
async def list_recreations(
    container: ContainerDep, user_id: UserIdDep,
) -> RecreationListResponse:
    recreations = await container.recreation_repo().list_for_user(user_id)
    return RecreationListResponse(recreations=[_to_recreation_response(r) for r in recreations])


@router.get(
    "/recreations/{recreation_id}",
    response_model=RecreationResponse,
    summary="Get a specific recreation detail",
)
async def get_recreation(
    recreation_id: str, container: ContainerDep, user_id: UserIdDep,
) -> RecreationResponse:
    rec = await container.recreation_repo().get(RecreationId(recreation_id))
    if rec is None or rec.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Recreation not found")
    return _to_recreation_response(rec)


@router.patch(
    "/recreations/{recreation_id}",
    response_model=RecreationResponse,
    summary="Update editable fields of a recreation draft",
)
async def update_recreation(
    recreation_id: str, body: UpdateRecreationRequest, container: ContainerDep, user_id: UserIdDep,
) -> RecreationResponse:
    repo = container.recreation_repo()
    rec = await repo.get(RecreationId(recreation_id))
    if rec is None or rec.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Recreation not found")
    
    if body.title is not None:
        rec.title = body.title
    if body.v2v_prompt is not None:
        rec.v2v_prompt = body.v2v_prompt
    if body.reference_description is not None:
        rec.reference_description = body.reference_description
    if body.beats is not None:
        rec.beats = [{"beat": b.beat, "duration_s": b.duration_s, "description": b.description} for b in body.beats]
    if body.audio_note is not None:
        rec.audio_note = body.audio_note
    if body.provider is not None:
        rec.provider = body.provider
    if body.video_model is not None:
        rec.model = body.video_model

    rec = await repo.save(rec)
    return _to_recreation_response(rec)


@router.post(
    "/recreations/{recreation_id}/run",
    summary="Execute a recreation draft",
)
async def run_recreation(
    recreation_id: str, container: ContainerDep, user_id: UserIdDep,
) -> dict[str, str]:
    repo = container.recreation_repo()
    rec = await repo.get(RecreationId(recreation_id))
    if rec is None or rec.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Recreation not found")

    from videocreator.domain.value_objects import DagSpec, DagNode
    from videocreator.infrastructure.queue.dag_executor import DagRun, DagExecutor

    # BASIC recreation: generate one clip from the plan's prompt via text_to_video
    # (a real, registry-backed capability). This is the "from scratch" path.
    # For keeping a real clip's head and regenerating only its ending from a cut
    # frame, use the Alternate Ending flow (/brain/recreations/alternate-ending),
    # which is image_to_video — NOT video_to_video (that has no provider/handler).
    nodes = [DagNode(
        id="render_0",
        capability="text_to_video",
        params={
            "prompt": rec.v2v_prompt,
            "provider": rec.provider or "veo",
            "model": rec.model,
        },
    )]
    
    spec = DagSpec(nodes=tuple(nodes))
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    run = DagRun(run_id=run_id, spec=spec)
    
    registry = container.run_registry()
    registry.register(run)
    bus = container.event_bus()

    async def _emit(rid: str, event: dict) -> None:
        await bus.publish(f"run:{rid}", event)

    executor = DagExecutor(container.capability_executor(), on_event=_emit)

    async def _execute() -> None:
        # Mark running
        rec.state = RecreationState.RUNNING
        await repo.save(rec)
        try:
            completed_run = await executor.run(run)
            rec.state = RecreationState.DONE
            
            # Persist result from render node
            result_node = completed_run.node_states.get("render_0")
            if result_node and result_node.result:
                rec.result = result_node.result
                
        except Exception:
            rec.state = RecreationState.FAILED
        finally:
            await repo.save(rec)

    asyncio.create_task(_execute())
    
    rec.run_id = run_id
    rec.state = RecreationState.RUNNING
    await repo.save(rec)
    
    return {"run_id": run_id}


# ---- Alternate Ending (ingest a clip, keep head, regenerate tail via i2v) ----
class IngestYouTubeRequest(BaseModel):
    url: str
    rights_ack: bool = False


class IngestResponse(BaseModel):
    source_id: str
    duration_s: float


class AlternateEndingRequest(BaseModel):
    source_id: str
    cut_at_s: float
    prompt: str
    tail_duration_s: float = 5.0


class AlternateEndingResponse(BaseModel):
    video_url: str | None
    duration_s: float


def _alt_source_dir(container: ContainerDep, source_id: str):
    from videocreator.shared.ids import generate_id
    base = container.settings.var_dir / "runs" / "alt_ending"
    # source_id is an opaque slug we mint; reject anything with path separators.
    if not source_id or "/" in source_id or "\\" in source_id or ".." in source_id:
        raise HTTPException(status_code=400, detail="invalid source_id")
    return base / source_id


@router.post("/recreations/ingest/upload", response_model=IngestResponse,
             summary="Ingest a dragged-and-dropped clip for an alternate ending")
async def ingest_upload(
    container: ContainerDep, user_id: UserIdDep, file: UploadFile = File(...),
) -> IngestResponse:
    from videocreator.infrastructure.publish.media_ingest import save_upload
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.shared.ids import generate_id

    source_id = generate_id("src")
    dest = _alt_source_dir(container, source_id)
    data = await file.read()
    try:
        path = save_upload(data, dest, filename=file.filename or "source.mp4")
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return IngestResponse(source_id=source_id, duration_s=probe_duration(path))


@router.post("/recreations/ingest/youtube", response_model=IngestResponse,
             summary="Ingest a YouTube clip (requires rights acknowledgement)")
async def ingest_youtube_ep(
    body: IngestYouTubeRequest, container: ContainerDep, user_id: UserIdDep,
) -> IngestResponse:
    from videocreator.infrastructure.publish.media_ingest import ingest_youtube
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.shared.ids import generate_id
    from videocreator.shared.errors import ValidationError, ProviderError

    source_id = generate_id("src")
    dest = _alt_source_dir(container, source_id)
    try:
        path = await asyncio.to_thread(
            ingest_youtube, body.url, dest, rights_ack=body.rights_ack,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return IngestResponse(source_id=source_id, duration_s=probe_duration(path))


@router.post("/recreations/alternate-ending", response_model=AlternateEndingResponse,
             summary="Keep the clip's head, regenerate the tail from the cut frame (i2v)")
async def alternate_ending(
    body: AlternateEndingRequest, container: ContainerDep, user_id: UserIdDep,
) -> AlternateEndingResponse:
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.shared.errors import ValidationError

    source = _alt_source_dir(container, body.source_id) / "source.mp4"
    if not source.exists():
        raise HTTPException(status_code=404, detail="source not found — ingest first")
    svc = container.alternate_ending_service()
    svc._work = _alt_source_dir(container, body.source_id)  # write outputs beside the source
    try:
        final = await asyncio.to_thread(
            svc.run, source, cut_at_s=body.cut_at_s, prompt=body.prompt,
            tail_duration_s=body.tail_duration_s,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Publish to the media bucket so the UI can stream it.
    storage = container.storage()
    key = f"alt_ending/{body.source_id}.mp4"
    await storage.put("media", key, final.read_bytes())
    url = await storage.url_for("media", key)
    return AlternateEndingResponse(video_url=url, duration_s=probe_duration(final))


@router.delete(
    "/recreations/{recreation_id}",
    status_code=204,
    summary="Delete a recreation draft",
)
async def delete_recreation(
    recreation_id: str, container: ContainerDep, user_id: UserIdDep,
) -> None:
    repo = container.recreation_repo()
    rec = await repo.get(RecreationId(recreation_id))
    if rec is None or rec.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Recreation not found")
    await repo.delete(RecreationId(recreation_id))


def _to_recreation_response(rec: Recreation) -> RecreationResponse:
    return RecreationResponse(
        id=str(rec.id),
        owner_id=str(rec.owner_id),
        state=rec.state.value,
        run_id=rec.run_id,
        title=rec.title,
        original=rec.original,
        niche=rec.niche,
        twist=rec.twist,
        v2v_prompt=rec.v2v_prompt,
        beats=[RecreationBeatResponse(
            beat=b.get("beat", ""), duration_s=b.get("duration_s", 0.0), description=b.get("description", ""),
        ) for b in rec.beats],
        audio_note=rec.audio_note,
        reference_description=rec.reference_description,
        fair_use=rec.fair_use,
        provider=rec.provider,
        model=rec.model,
        result=rec.result,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
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
