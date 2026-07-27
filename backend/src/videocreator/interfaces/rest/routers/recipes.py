"""Recipe endpoints — DAG runs (SSE), Director's Chat, template gallery (§16.15).

Director's Chat takes the DagSpec inline for now: recipes aren't persisted
per-episode yet, so the client owns the recipe document and round-trips it.
`POST /runs` is the "Generar" button: it executes a recipe through the
CapabilityExecutor in the background and streams progress over SSE.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from videocreator.domain.value_objects import DagSpec
from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    DagSpecSchema,
    DirectorChatRequest,
    DirectorChatResponse,
    RunSnapshotResponse,
    TemplateResponse,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["recipes"])

#: Fire-and-forget DAG runs. asyncio only holds a weak reference to a running
#: task, so without a strong one here a run can be garbage-collected mid-flight.
#: Tasks remove themselves when they finish.
_background_tasks: set[asyncio.Task[None]] = set()


def _to_spec_schema(spec: DagSpec) -> DagSpecSchema:
    return DagSpecSchema.model_validate(spec.model_dump())


@router.post(
    "/director/chat",
    response_model=DirectorChatResponse,
    summary="Conversational edit of a render recipe (JSON Patch RFC 6902)",
)
async def director_chat(
    body: DirectorChatRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> DirectorChatResponse:
    try:
        spec = DagSpec.model_validate(body.spec.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid recipe: {e}") from e
    try:
        result = await uc.brain.director_chat.execute(spec, body.message)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return DirectorChatResponse(
        patch=list(result.patch),
        explanation=result.explanation,
        spec=_to_spec_schema(result.spec),
    )


@router.get(
    "/templates",
    response_model=list[TemplateResponse],
    summary="List the render template gallery",
)
async def list_templates(container: ContainerDep, user_id: UserIdDep) -> list[TemplateResponse]:
    return [_to_template_response(t) for t in container.template_gallery().list()]


@router.get(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    summary="Get one template",
)
async def get_template(
    template_id: str, container: ContainerDep, user_id: UserIdDep,
) -> TemplateResponse:
    template = container.template_gallery().get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"template '{template_id}' not found")
    return _to_template_response(template)


def _to_template_response(t) -> TemplateResponse:  # type: ignore[no-untyped-def]
    return TemplateResponse(
        id=t.id, name=t.name, description=t.description,
        tags=list(t.tags), preview=t.preview,
        dag=_to_spec_schema(t.dag),
    )


@router.post(
    "/runs",
    response_model=RunSnapshotResponse,
    status_code=202,
    summary="Execute a recipe — starts a DAG run in the background",
)
async def start_run(
    body: DagSpecSchema, container: ContainerDep, user_id: UserIdDep,
) -> RunSnapshotResponse:
    try:
        spec = DagSpec.model_validate(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid recipe: {e}") from e

    from videocreator.infrastructure.queue.dag_executor import DagExecutor, DagRun

    run = DagRun(run_id=f"run_{uuid.uuid4().hex[:12]}", spec=spec)
    registry = container.run_registry()
    registry.register(run)
    bus = container.event_bus()

    async def _emit(run_id: str, event: dict) -> None:
        await bus.publish(f"run:{run_id}", event)

    executor = DagExecutor(container.capability_executor(), on_event=_emit)

    async def _execute() -> None:
        try:
            await executor.run(run)
        except Exception as e:  # defensive: a crashed run must stay inspectable
            log.error("run.crashed", run_id=run.run_id, error=str(e))

    task = asyncio.create_task(_execute())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    snapshot = registry.snapshot(run.run_id)
    assert snapshot is not None
    return RunSnapshotResponse.model_validate(snapshot)


@router.get(
    "/runs/{run_id}",
    response_model=RunSnapshotResponse,
    summary="Snapshot of a DAG run's node states (timeline UI)",
)
async def get_run(
    run_id: str, container: ContainerDep, user_id: UserIdDep,
) -> RunSnapshotResponse:
    snapshot = container.run_registry().snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    return RunSnapshotResponse.model_validate(snapshot)


@router.get(
    "/runs/{run_id}/events",
    summary="Server-Sent Events stream of DAG run progress",
    response_class=StreamingResponse,
)
async def stream_run_events(
    run_id: str, container: ContainerDep, user_id: UserIdDep,
) -> StreamingResponse:
    if container.run_registry().get(run_id) is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    bus = container.event_bus()

    async def _gen():  # type: ignore[no-untyped-def]
        try:
            async for event in bus.subscribe(f"run:{run_id}"):
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            log.info("sse.run.disconnected", run_id=run_id)
            raise

    return StreamingResponse(_gen(), media_type="text/event-stream")


__all__ = ["router"]
