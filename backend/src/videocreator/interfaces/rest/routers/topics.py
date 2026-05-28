"""Topic endpoints — list + LLM-driven generation."""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    GenerateTopicsRequest,
    TopicResponse,
)
from videocreator.shared.ids import PodId

router = APIRouter(prefix="/pods/{pod_id}/topics", tags=["topics"])


def _to_response(t) -> TopicResponse:  # type: ignore[no-untyped-def]
    return TopicResponse(
        id=t.id, pod_id=t.pod_id, title=t.title, description=t.description,
        status=t.status, educational_value=t.educational_value, created_at=t.created_at,
    )


@router.get("", response_model=list[TopicResponse], summary="List pod topics")
async def list_topics(
    pod_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> list[TopicResponse]:
    topics = await uc.topics.list.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return [_to_response(t) for t in topics]


@router.post(
    "/generate", response_model=list[TopicResponse],
    summary="Generate fresh topics via the LLM",
)
async def generate_topics(
    pod_id: str, body: GenerateTopicsRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> list[TopicResponse]:
    topics = await uc.topics.generate.execute(
        pod_id=PodId(pod_id), requester_id=user_id, count=body.count,
    )
    return [_to_response(t) for t in topics]


__all__ = ["router"]
