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
from videocreator.domain.ports import LLMPort, PodRepository, TopicRepository
from videocreator.domain.value_objects import TopicStatus
from videocreator.shared.errors import ForbiddenError, PodNotFound, ProviderError
from videocreator.shared.ids import PodId, UserId, new_topic_id

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
    series_context: str | None, count: int,
) -> str:
    ctx = series_context.strip() if series_context else "(no extra context)"
    return (
        f"You are a curriculum designer for the educational video series '{series_name}'.\n"
        f"Audience: {target_audience}. Language: {language}.\n"
        f"Series context: {ctx}\n\n"
        f"Propose {count} fresh topic ideas. Each topic must be specific, "
        f"educationally valuable, and suitable for a short (~2-3 minute) video.\n"
        f"Return strict JSON matching the supplied schema."
    )


@dataclass(frozen=True, slots=True)
class GenerateTopics:
    pod_repo: PodRepository
    topic_repo: TopicRepository
    llm: LLMPort

    async def execute(
        self, *, pod_id: PodId, requester_id: UserId, count: int = 5,
    ) -> list[Topic]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")

        prompt = _render_topic_prompt(
            series_name=pod.config.series_name,
            target_audience=pod.config.target_audience,
            language=pod.config.language,
            series_context=pod.config.series_context,
            count=count,
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


__all__ = ["GenerateTopics", "ListTopics"]
