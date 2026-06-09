"""Job endpoints — polling + SSE stream backed by the EventBus."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import JobResponse
from videocreator.shared.ids import JobId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_response(j) -> JobResponse:  # type: ignore[no-untyped-def]
    kind = j.kind.value if hasattr(j.kind, "value") else str(j.kind)
    return JobResponse(
        id=j.id, owner_id=j.owner_id, kind=kind,
        state=j.state, progress=j.progress, message=j.message,
        payload=j.payload, result=j.result, error=j.error,
        created_at=j.created_at, updated_at=j.updated_at,
    )


@router.get("", response_model=list[JobResponse], summary="List recent jobs")
async def list_jobs(
    uc: UseCasesDep, user_id: UserIdDep,
    limit: int = Query(50, ge=1, le=200),
) -> list[JobResponse]:
    jobs = await uc.jobs.list_recent.execute(requester_id=user_id, limit=limit)
    return [_to_response(j) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse, summary="Get a job")
async def get_job(job_id: str, uc: UseCasesDep, user_id: UserIdDep) -> JobResponse:
    job = await uc.jobs.get.execute(job_id=JobId(job_id), requester_id=user_id)
    return _to_response(job)


@router.delete(
    "/{job_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a finished job record",
)
async def delete_job(job_id: str, uc: UseCasesDep, user_id: UserIdDep) -> None:
    await uc.jobs.delete.execute(job_id=JobId(job_id), requester_id=user_id)


@router.get(
    "/{job_id}/events",
    summary="Server-Sent Events stream of job progress",
    response_class=StreamingResponse,
)
async def stream_job_events(
    job_id: str, uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> StreamingResponse:
    # Authorize before opening the stream.
    await uc.jobs.get.execute(job_id=JobId(job_id), requester_id=user_id)
    bus = container.event_bus()

    async def _gen():  # type: ignore[no-untyped-def]
        try:
            async for event in bus.subscribe(f"job:{job_id}"):
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            log.info("sse.disconnected", job_id=job_id)
            raise

    return StreamingResponse(_gen(), media_type="text/event-stream")


__all__ = ["router"]
