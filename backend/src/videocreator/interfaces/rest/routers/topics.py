"""Topic endpoints — list + LLM-driven generation."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    GenerateTopicsRequest,
    TopicResponse,
    UpdateTopicRequest,
)
from videocreator.shared.ids import PodId, TopicId

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
        use_trends=body.use_trends,
    )
    return [_to_response(t) for t in topics]


@router.patch("/{topic_id}", response_model=TopicResponse, summary="Edit a topic")
async def update_topic(
    pod_id: str, topic_id: str, body: UpdateTopicRequest,
    uc: UseCasesDep, user_id: UserIdDep,
) -> TopicResponse:
    del pod_id
    topic = await uc.topics.update.execute(
        topic_id=TopicId(topic_id), requester_id=user_id,
        title=body.title, description=body.description,
        educational_value=body.educational_value, status=body.status,
    )
    return _to_response(topic)


@router.delete(
    "/{topic_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a topic",
)
async def delete_topic(
    pod_id: str, topic_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    del pod_id
    await uc.topics.delete.execute(topic_id=TopicId(topic_id), requester_id=user_id)


__all__ = ["router"]
