"""Script generation use case.

Renders a Gemini-compatible JSON schema for scenes and persists the resulting
Script entity. This is the application-layer port wrapper around the existing
prompt engineering in `src/engines/script/` — kept minimal here so the engines
can be lifted into this layer incrementally.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Scene, Script
from videocreator.domain.ports import (
    LLMPort,
    PodRepository,
    ScriptRepository,
    TopicRepository,
)
from videocreator.shared.errors import (
    ForbiddenError,
    PodNotFound,
    ProviderError,
)
from videocreator.shared.ids import (
    PodId,
    ScriptId,
    SceneId,
    TopicId,
    UserId,
    new_scene_id,
    new_script_id,
)


_SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "visual_prompt": {"type": "string"},
                    "audio_text": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "camera_shot": {"type": "string"},
                    "camera_movement": {"type": "string"},
                    "camera_angle": {"type": "string"},
                    "transition": {"type": "string"},
                },
                "required": ["visual_prompt", "audio_text"],
            },
        },
    },
    "required": ["title", "scenes"],
}


def _render_script_prompt(
    *, series_name: str, language: str, target_duration_s: int,
    topic_title: str, topic_description: str | None,
    series_context: str | None,
) -> str:
    ctx = series_context.strip() if series_context else "(no extra context)"
    desc = topic_description.strip() if topic_description else "(no description)"
    return (
        f"You are the head writer for '{series_name}'. Language: {language}.\n"
        f"Series context: {ctx}\n\n"
        f"Topic: {topic_title}\nDetails: {desc}\n\n"
        f"Write a tight, engaging script of about {target_duration_s} seconds total. "
        f"Break it into 8-second scenes (~{max(1, target_duration_s // 8)} scenes). "
        f"Each scene needs a vivid visual_prompt (suitable for a text-to-video model) "
        f"and a concise audio_text (narration). Camera fields are optional but useful.\n"
        f"Return strict JSON matching the supplied schema."
    )


def _to_scene(idx: int, raw: dict[str, Any]) -> Scene:
    transition_raw = raw.get("transition", "cut")
    transition = transition_raw if transition_raw in {"cut", "continue", "scene_change"} else "cut"
    sid: SceneId = new_scene_id()
    return Scene(
        id=sid,
        index=idx,
        visual_prompt=str(raw["visual_prompt"]),
        audio_text=raw.get("audio_text"),
        transition=transition,  # type: ignore[arg-type]
        duration_s=float(raw.get("duration_s", 8.0)),
        camera_shot=raw.get("camera_shot"),
        camera_movement=raw.get("camera_movement"),
        camera_angle=raw.get("camera_angle"),
    )


@dataclass(frozen=True, slots=True)
class GenerateScript:
    pod_repo: PodRepository
    topic_repo: TopicRepository
    script_repo: ScriptRepository
    llm: LLMPort

    async def execute(
        self, *, pod_id: PodId, topic_id: TopicId, requester_id: UserId,
    ) -> Script:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        topic = await self.topic_repo.get(topic_id)
        if topic is None or topic.pod_id != pod_id:
            raise PodNotFound(f"topic {topic_id} not found in pod {pod_id}")

        prompt = _render_script_prompt(
            series_name=pod.config.series_name,
            language=pod.config.language,
            target_duration_s=pod.config.duration_seconds,
            topic_title=topic.title,
            topic_description=topic.description,
            series_context=pod.config.series_context,
        )
        raw = await self.llm.complete(prompt, response_schema=_SCENE_SCHEMA, temperature=0.8)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        scenes = [_to_scene(i, s) for i, s in enumerate(data.get("scenes") or [])
                  if isinstance(s, dict) and "visual_prompt" in s]
        script_id: ScriptId = new_script_id()
        script = Script(
            id=script_id,
            pod_id=pod_id,
            topic_id=topic_id,
            title=str(data.get("title") or topic.title),
            summary=data.get("summary"),
            scenes=scenes,
        )
        return await self.script_repo.save(script)


@dataclass(frozen=True, slots=True)
class ListScripts:
    pod_repo: PodRepository
    script_repo: ScriptRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> list[Script]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return await self.script_repo.list_for_pod(pod_id)


__all__ = ["GenerateScript", "ListScripts"]
