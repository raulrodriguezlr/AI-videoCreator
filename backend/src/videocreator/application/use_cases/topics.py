"""Topic generation & listing use cases.

`GenerateTopics` calls the LLM port with a Gemini-compatible JSON schema and
persists the resulting topics. The prompt rendering lives here (application
layer) rather than in the adapter so swapping LLMs does not require rewriting
the prompts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Topic
from videocreator.domain.ports import (
    LLMPort,
    PodRepository,
    TopicRepository,
    TrendSourcePort,
)
from videocreator.domain.value_objects import TopicStatus
from videocreator.shared.errors import (
    ForbiddenError,
    NotFoundError,
    PodNotFound,
    ProviderError,
)
from videocreator.shared.ids import PodId, TopicId, UserId, new_topic_id
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


async def _owned_topic(
    topic_repo: TopicRepository, pod_repo: PodRepository,
    topic_id: TopicId, requester_id: UserId,
) -> Topic:
    topic = await topic_repo.get(topic_id)
    if topic is None:
        raise NotFoundError(f"topic {topic_id} not found")
    pod = await pod_repo.get(topic.pod_id)
    if pod is None or not pod.is_owned_by(requester_id):
        raise ForbiddenError("topic belongs to a pod owned by a different user")
    return topic

_TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "educational_value": {"type": "string"},
                },
                "required": ["title", "description"],
            },
        }
    },
    "required": ["topics"],
}


def _render_topic_prompt(
    *, series_name: str, target_audience: str, language: str,
    series_context: str | None, count: int, trends: list[str] | None = None,
) -> str:
    ctx = series_context.strip() if series_context else "(no extra context)"
    trend_block = ""
    if trends:
        joined = ", ".join(trends)
        trend_block = (
            f"\nCurrent trending search terms to take inspiration from where they "
            f"fit the series (adapt, don't copy verbatim): {joined}.\n"
        )
    return (
        f"You are a curriculum designer for the educational video series '{series_name}'.\n"
        f"Audience: {target_audience}. Language: {language}.\n"
        f"Series context: {ctx}\n"
        f"{trend_block}\n"
        f"Propose {count} fresh topic ideas. Each topic must be specific, "
        f"educationally valuable, and suitable for a short (~2-3 minute) video.\n"
        f"Return strict JSON matching the supplied schema."
    )


@dataclass(frozen=True, slots=True)
class GenerateTopics:
    pod_repo: PodRepository
    topic_repo: TopicRepository
    llm: LLMPort
    trends: TrendSourcePort | None = None

    async def execute(
        self, *, pod_id: PodId, requester_id: UserId, count: int = 5,
        use_trends: bool = False,
    ) -> list[Topic]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")

        trend_terms: list[str] = []
        if use_trends and self.trends is not None:
            try:
                trend_terms = await self.trends.fetch(language=pod.config.language, limit=15)
            except Exception:
                # Trends are best-effort grounding, not a requirement — generate
                # topics without them rather than failing the whole request.
                log.warning("topics.trends_unavailable", pod_id=str(pod_id), exc_info=True)

        prompt = _render_topic_prompt(
            series_name=pod.config.series_name,
            target_audience=pod.config.target_audience,
            language=pod.config.language,
            series_context=pod.config.series_context,
            count=count,
            trends=trend_terms,
        )
        raw = await self.llm.complete(prompt, response_schema=_TOPIC_SCHEMA, temperature=0.9)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        topics: list[Topic] = []
        for item in data.get("topics", []):
            if not isinstance(item, dict) or "title" not in item:
                continue
            topic = Topic(
                id=new_topic_id(),
                pod_id=pod_id,
                title=str(item["title"]),
                description=item.get("description"),
                educational_value=item.get("educational_value"),
                status=TopicStatus.PENDING,
            )
            topics.append(await self.topic_repo.save(topic))
        return topics


@dataclass(frozen=True, slots=True)
class ListTopics:
    pod_repo: PodRepository
    topic_repo: TopicRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> list[Topic]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return await self.topic_repo.list_for_pod(pod_id)


@dataclass(frozen=True, slots=True)
class UpdateTopic:
    pod_repo: PodRepository
    topic_repo: TopicRepository

    async def execute(
        self, *, topic_id: TopicId, requester_id: UserId,
        title: str | None = None, description: str | None = None,
        educational_value: str | None = None, status: TopicStatus | None = None,
    ) -> Topic:
        topic = await _owned_topic(self.topic_repo, self.pod_repo, topic_id, requester_id)
        updated = topic.model_copy(update={
            k: v for k, v in {
                "title": title.strip() if title else None,
                "description": description,
                "educational_value": educational_value,
                "status": status,
            }.items() if v is not None
        })
        return await self.topic_repo.save(updated)


@dataclass(frozen=True, slots=True)
class DeleteTopic:
    pod_repo: PodRepository
    topic_repo: TopicRepository

    async def execute(self, *, topic_id: TopicId, requester_id: UserId) -> None:
        await _owned_topic(self.topic_repo, self.pod_repo, topic_id, requester_id)
        await self.topic_repo.delete(topic_id)


__all__ = ["DeleteTopic", "GenerateTopics", "ListTopics", "UpdateTopic"]
