"""Tests for the two-pass script pipeline: WriteStory (creative) → GenerateScript.

Fakes for repos + LLM let us assert the prompts each pass builds without any
network: the creative pass must produce prose (no schema), and the director pass
must adapt the supplied narrative and carry the dialogue-quality rules.
"""
from __future__ import annotations

import json
from typing import Any

from videocreator.application.use_cases.scripts import (
    _DIALOGUE_QUALITY,
    GenerateScript,
    WriteStory,
    _format_characters,
    _role_group,
    _style_label,
)
from videocreator.domain.entities import LOCAL_USER_ID, Character, Pod, PodConfig, Topic
from videocreator.domain.value_objects import StyleProfile
from videocreator.shared.ids import new_character_id, new_pod_id, new_topic_id


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def complete(self, prompt: str, *, response_schema=None, temperature=0.7, **_):
        self.calls.append({"prompt": prompt, "schema": response_schema, "temp": temperature})
        return self.reply


class _PodRepo:
    def __init__(self, pod: Pod) -> None:
        self.pod = pod

    async def get(self, pod_id):
        return self.pod if pod_id == self.pod.id else None

    async def save(self, pod):
        self.pod = pod
        return pod


class _TopicRepo:
    def __init__(self, topic: Topic) -> None:
        self.topic = topic

    async def get(self, topic_id):
        return self.topic if topic_id == self.topic.id else None


class _CharRepo:
    def __init__(self, chars: list[Character]) -> None:
        self.chars = chars

    async def list_for_pod(self, pod_id):
        return self.chars


class _ScriptRepo:
    def __init__(self) -> None:
        self.saved = None

    async def save(self, script):
        self.saved = script
        return script


def _fixture():
    pod = Pod(id=new_pod_id(), owner_id=LOCAL_USER_ID, name="Tico",
              config=PodConfig(series_name="Las Aventuras de Tico", language="es-ES",
                               duration_seconds=60))
    topic = Topic(id=new_topic_id(), pod_id=pod.id, title="El fútbol",
                  description="Tico aprende perseverancia")
    char = Character(id=new_character_id(), pod_id=pod.id, name="Tico")
    return pod, topic, char


async def test_write_story_uses_prose_not_schema() -> None:
    pod, topic, char = _fixture()
    llm = _FakeLLM("Había una vez Tico, que soñaba con el fútbol...")
    uc = WriteStory(_PodRepo(pod), _TopicRepo(topic), _CharRepo([char]), llm)  # type: ignore[arg-type]

    out = await uc.execute(pod_id=pod.id, topic_id=topic.id, requester_id=LOCAL_USER_ID)

    assert out.startswith("Había una vez")
    call = llm.calls[0]
    assert call["schema"] is None          # creative pass → NO json schema
    assert call["temp"] == 0.9             # higher temperature for creativity
    # prose prompt forbids JSON/camera and demands the 3-act weighting
    assert "NOT as " in call["prompt"] and "JSON" in call["prompt"]
    assert "~70%" in call["prompt"]        # Act 2 carries the weight
    assert "FORBIDDEN" in call["prompt"]   # the empty-exclamation ban


async def test_generate_adapts_supplied_narrative() -> None:
    pod, topic, char = _fixture()
    scene = {"visual_prompt": "Tico kicks the ball", "audio_text": "real line",
             "camera": {"shot_type": "medium", "movement": "static", "angle": "eye_level"},
             "mood": "joyful", "lighting": "bright_daylight",
             "transition_to_next": "cut", "duration_seconds": 5}
    llm = _FakeLLM(json.dumps({"title": "T", "scenes": [scene]}))
    uc = GenerateScript(_PodRepo(pod), _TopicRepo(topic), _ScriptRepo(),
                        _CharRepo([char]), llm)  # type: ignore[arg-type]

    narrative = "Tico practica una y otra vez hasta lograr el gol decisivo."
    await uc.execute(pod_id=pod.id, topic_id=topic.id, requester_id=LOCAL_USER_ID,
                     story_narrative=narrative)

    prompt = llm.calls[0]["prompt"]
    assert narrative in prompt                       # the story is injected
    assert "ADAPT THIS" in prompt                    # director mode, not invent
    assert "technical director" in prompt
    assert _DIALOGUE_QUALITY.split("\n", 1)[0] in prompt  # quality rules carried


def test_characters_grouped_by_role_and_registered_only() -> None:
    pid = new_pod_id()

    def C(name, role):
        return Character(id=new_character_id(), pod_id=pid, name=name, role=role)

    assert _role_group("protagonist") == "protagonist"
    assert _role_group("supporting") == "secondary"
    assert _role_group("antagonist") == "antagonist"

    out = _format_characters([C("Tico", "protagonist"), C("Mara", "secondary"),
                              C("Lobo", "antagonist")])
    assert "NEVER invent" in out                      # registered-only rule
    assert "ALWAYS present" in out                    # protagonist anchors
    assert "only if they fit this episode" in out     # secondaries optional
    assert "Tico" in out and "Mara" in out and "Lobo" in out


def test_no_explicit_protagonist_promotes_first() -> None:
    # Legacy data: every character defaults to "supporting" → the first becomes
    # the de-facto lead so the story still has an anchor.
    pid = new_pod_id()
    out = _format_characters([
        Character(id=new_character_id(), pod_id=pid, name="Pina", role="supporting"),
        Character(id=new_character_id(), pod_id=pid, name="Otro", role="supporting"),
    ])
    proto_block = out.split("always present:", 1)[1].split("SECONDARY")[0]
    assert "Pina" in proto_block and "Otro" not in proto_block


def test_style_label_uses_profile_so_dropdown_changes_visuals() -> None:
    # Changing the style_profile must change the effective style even if the
    # free-text art_style is empty (the reported bug).
    assert "photorealistic" in _style_label(StyleProfile.PHOTOREAL_DOC, None)
    assert "anime" in _style_label(StyleProfile.ANIME_2D, "")
    # free-text detail is appended, not replaced
    label = _style_label(StyleProfile.CINEMATIC_3D, "noir, neon rain")
    assert "cinematic 3D" in label and "noir, neon rain" in label


async def test_generate_uses_style_profile_in_prompt() -> None:
    pod, topic, char = _fixture()
    pod.config.style_profile = StyleProfile.PHOTOREAL_DOC
    llm = _FakeLLM(json.dumps({"title": "T", "scenes": []}))
    uc = GenerateScript(_PodRepo(pod), _TopicRepo(topic), _ScriptRepo(),
                        _CharRepo([char]), llm)  # type: ignore[arg-type]
    await uc.execute(pod_id=pod.id, topic_id=topic.id, requester_id=LOCAL_USER_ID)
    assert "photorealistic" in llm.calls[0]["prompt"]


async def test_generate_without_narrative_keeps_inventor_role() -> None:
    pod, topic, char = _fixture()
    llm = _FakeLLM(json.dumps({"title": "T", "scenes": []}))
    uc = GenerateScript(_PodRepo(pod), _TopicRepo(topic), _ScriptRepo(),
                        _CharRepo([char]), llm)  # type: ignore[arg-type]

    await uc.execute(pod_id=pod.id, topic_id=topic.id, requester_id=LOCAL_USER_ID)

    prompt = llm.calls[0]["prompt"]
    assert "head director and screenwriter" in prompt   # invent path
    assert "ADAPT THIS" not in prompt
    assert _DIALOGUE_QUALITY.split("\n", 1)[0] in prompt  # rules still present
