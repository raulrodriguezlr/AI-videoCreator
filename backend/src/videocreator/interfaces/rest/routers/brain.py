"""Brain endpoints — video analysis, trend radar, scene recreation."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from videocreator.domain.entities import Recreation
from videocreator.domain.services.provider_hints import filter_available, hint_for
from videocreator.domain.value_objects import RecreationState
from videocreator.infrastructure.trends.google_trends import GoogleTrendsRss
from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    AnalyzeVideoRequest,
    FairUseResponse,
    GenomeBeatResponse,
    GenomeHookResponse,
    PlanRecreationRequest,
    RecreationBeatResponse,
    RecreationListResponse,
    RecreationPlanResponse,
    RecreationResponse,
    SceneCandidateResponse,
    SceneTrendMatchRequest,
    SceneTrendMatchResponse,
    UpdateRecreationRequest,
    ViralGenomeResponse,
)
from videocreator.shared.ids import RecreationId, new_recreation_id

router = APIRouter(prefix="/brain", tags=["brain"])

#: Fire-and-forget run tasks. asyncio only holds a weak reference to a running
#: task, so without a strong one here a recreation run can be garbage-collected
#: mid-flight. Tasks remove themselves when they finish.
_background_tasks: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Schedule a background coroutine, keeping it alive until it completes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post(
    "/analyze",
    response_model=ViralGenomeResponse,
    summary=(
        "Analyze a video's context/URL as text and extract its viral genome "
        "(no video ingestion)"
    ),
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
        beats=[
            {"beat": b.beat, "duration_s": b.duration_s, "description": b.description}
            for b in plan.beats
        ],
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
        rec.beats = [
            {"beat": b.beat, "duration_s": b.duration_s, "description": b.description}
            for b in body.beats
        ]
    if body.audio_note is not None:
        rec.audio_note = body.audio_note
    if body.provider is not None:
        rec.provider = body.provider
    if body.video_model is not None:
        rec.model = body.video_model
    if body.source_id is not None:
        rec.source_id = body.source_id

    rec = await repo.save(rec)
    return _to_recreation_response(rec)


def _resolve_recreation_provider(
    container: ContainerDep, rec: Recreation, capability: str = "text_to_video",
) -> str:
    """Resolve the actual provider for a recreation run (one capability).

    Never silently defaults to "veo" — that provider has no registered handler
    in this build (§ engine→DAG migration in progress) and would fail opaquely
    once the DAG actually executes. An explicit `rec.provider` is validated
    against what this build knows about; otherwise the first provider that
    declares `capability` (default `text_to_video`; `video_to_video` for a
    recreation with an attached source clip — see `_resolve_recreation_v2v`) in
    the SDK registry is picked. Raises 422 (listing what's available) when
    neither resolves.
    """
    available = container.available_provider_names()
    if rec.provider:
        if rec.provider not in available:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Provider '{rec.provider}' no está disponible. "
                    f"Disponibles: {sorted(available)}"
                ),
            )
        return rec.provider

    capable = [lp.manifest.id for lp in container.provider_registry().find(capability)]
    if not capable:
        raise HTTPException(
            status_code=422,
            detail=f"No hay ningún provider disponible con la capability '{capability}'.",
        )
    return capable[0]


def _resolve_recreation_v2v(container: ContainerDep, rec: Recreation) -> tuple[str, str | None]:
    """Resolve (provider, model) for a video_to_video recreation run.

    Reuses `_resolve_recreation_provider` for the provider (now capability-
    aware); then picks a model: `rec.model` if pinned, else the first model the
    resolved provider declares for `video_to_video` — preferring
    "gemini-omni-flash" (the reference video-editing model) when present.
    Raises 422 when the provider has no matching model at all, instead of
    letting the adapter silently fall back to a non-editing model.
    """
    provider = _resolve_recreation_provider(container, rec, capability="video_to_video")
    if rec.model:
        return provider, rec.model
    loaded = container.provider_registry().get(provider)
    capable = (
        [m.id for m in loaded.manifest.models if "video_to_video" in m.capabilities]
        if loaded else []
    )
    if not capable:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El provider '{provider}' no declara ningún modelo con la "
                "capability 'video_to_video' — elige otro provider o fija un modelo."
            ),
        )
    model = "gemini-omni-flash" if "gemini-omni-flash" in capable else capable[0]
    return provider, model


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

    from videocreator.domain.value_objects import DagNode, DagSpec
    from videocreator.infrastructure.queue.dag_executor import DagExecutor, DagRun

    # A recreation with a real clip attached (ingested via the Alternate-Ending
    # upload/YouTube endpoints, PATCHed onto the draft as `source_id`) EDITS
    # that footage through video_to_video (e.g. Gemini Omni Flash) instead of
    # generating one from scratch — same "keep what's real" idea as Alternate
    # Ending's head+i2v-tail, but applied to the whole clip.
    source_path = (
        _alt_source_dir(container, rec.source_id) / "source.mp4" if rec.source_id else None
    )
    if source_path is not None and source_path.exists():
        from videocreator.application.use_cases.alternate_ending import probe_duration

        provider, model = _resolve_recreation_v2v(container, rec)
        nodes = [DagNode(
            id="render_0",
            capability="video_to_video",
            params={
                "prompt": rec.v2v_prompt,
                "provider": provider,
                "model": model,
                "input_video_path": str(source_path),
                # ffprobe is a sync subprocess — keep it off the event loop.
                "duration_s": await asyncio.to_thread(probe_duration, source_path),
            },
        )]
    else:
        provider = _resolve_recreation_provider(container, rec)
        # BASIC recreation: generate one clip from the plan's prompt via
        # text_to_video (a real, registry-backed capability). This is the
        # "from scratch" path, used whenever no source clip is attached. For
        # keeping only a clip's head and regenerating its ending from a cut
        # frame, see the Alternate Ending flow (/brain/recreations/alternate-ending).
        nodes = [DagNode(
            id="render_0",
            capability="text_to_video",
            params={
                "prompt": rec.v2v_prompt,
                "provider": provider,
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

    _spawn(_execute())

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
    #: "i2v" (default, back-compat): regenerate the tail from a still frame.
    #: "edit": feed the REAL tail clip to a video_to_video editing model
    #: (e.g. Gemini Omni Flash) instead of regenerating it from scratch.
    mode: Literal["i2v", "edit"] = "i2v"
    provider: str | None = None
    model: str | None = None


class AlternateEndingResponse(BaseModel):
    video_url: str | None
    duration_s: float


def _alt_source_dir(container: ContainerDep, source_id: str):
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
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.infrastructure.publish.media_ingest import save_upload
    from videocreator.shared.ids import generate_id

    source_id = generate_id("src")
    dest = _alt_source_dir(container, source_id)
    data = await file.read()
    try:
        path = save_upload(data, dest, filename=file.filename or "source.mp4")
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return IngestResponse(source_id=source_id, duration_s=probe_duration(path))


@router.post("/recreations/ingest/youtube", response_model=IngestResponse,
             summary="Ingest a YouTube clip (requires rights acknowledgement)")
async def ingest_youtube_ep(
    body: IngestYouTubeRequest, container: ContainerDep, user_id: UserIdDep,
) -> IngestResponse:
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.infrastructure.publish.media_ingest import ingest_youtube
    from videocreator.shared.errors import ProviderError, ValidationError
    from videocreator.shared.ids import generate_id

    source_id = generate_id("src")
    dest = _alt_source_dir(container, source_id)
    try:
        path = await asyncio.to_thread(
            ingest_youtube, body.url, dest, rights_ack=body.rights_ack,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return IngestResponse(source_id=source_id, duration_s=probe_duration(path))


@router.post("/recreations/alternate-ending", response_model=AlternateEndingResponse,
             summary="Keep the clip's head, change the tail — i2v regen or v2v edit")
async def alternate_ending(
    body: AlternateEndingRequest, container: ContainerDep, user_id: UserIdDep,
) -> AlternateEndingResponse:
    from videocreator.application.use_cases.alternate_ending import probe_duration
    from videocreator.shared.errors import ValidationError

    source = _alt_source_dir(container, body.source_id) / "source.mp4"
    if not source.exists():
        raise HTTPException(status_code=404, detail="source not found — ingest first")
    svc = container.alternate_ending_service(provider=body.provider, model=body.model)
    svc._work = _alt_source_dir(container, body.source_id)  # write outputs beside the source
    try:
        final = await asyncio.to_thread(
            svc.run, source, cut_at_s=body.cut_at_s, prompt=body.prompt,
            tail_duration_s=body.tail_duration_s, mode=body.mode,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
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
            beat=b.get("beat", ""),
            duration_s=b.get("duration_s", 0.0),
            description=b.get("description", ""),
        ) for b in rec.beats],
        audio_note=rec.audio_note,
        reference_description=rec.reference_description,
        fair_use=rec.fair_use,
        provider=rec.provider,
        model=rec.model,
        source_id=rec.source_id,
        result=rec.result,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post(
    "/recreations/trend-match",
    response_model=SceneTrendMatchResponse,
    summary="Match trend terms to famous scenes worth recreating",
)
async def scene_trend_match(
    body: SceneTrendMatchRequest,
    uc: UseCasesDep,
    container: ContainerDep,
    user_id: UserIdDep,
) -> SceneTrendMatchResponse:
    terms = body.terms
    # "live" is also the right label when the caller supplied their own terms
    # (no auto-fetch happened, so there's nothing stale/generic to flag).
    trends_source: str = "live"
    if not terms:
        trend_source = container.trend_source()
        if isinstance(trend_source, GoogleTrendsRss):
            fetched = await trend_source.fetch_with_source(limit=15)
            terms, trends_source = fetched.terms, fetched.source
        else:
            terms = await trend_source.fetch(limit=15)
    candidates = await uc.brain.scene_trend_match.execute(terms)
    return SceneTrendMatchResponse(
        candidates=[SceneCandidateResponse(
            term=c.term, scene=c.scene, why_trending=c.why_trending,
        ) for c in candidates],
        trends_source=trends_source,  # type: ignore[arg-type]
    )


__all__ = ["router"]
