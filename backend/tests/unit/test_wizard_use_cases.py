"""Tests for the AI Pod Wizard use cases.

The LLM and repositories are faked. `DraftPodBlueprint` is exercised against a
canned JSON payload (parsing, style coercion, capping, error paths) and
`CreatePodFromBlueprint` is checked for correct materialization into a pod with
its characters and seed topics.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.wizard import (
    CreatePodFromBlueprint,
    DraftPodBlueprint,
)
from videocreator.domain.entities import Character, Pod, PodConfig, Topic
from videocreator.domain.value_objects import (
    CharacterBlueprint,
    CharacterMode,
    ContentType,
    DurationStrategy,
    GenerationMode,
    PodBlueprint,
    SeriesBible,
    StyleProfile,
    content_profile,
)
from videocreator.shared.errors import ConflictError, ProviderError, ValidationError
from videocreator.shared.ids import CharacterId, PodId, TopicId, UserId

OWNER = UserId("usr_1")


# ============================================================================
# Fakes
# ============================================================================
class _FakeLLM:
    def __init__(self, payload: dict[str, Any] | str) -> None:
        self._raw = payload if isinstance(payload, str) else json.dumps(payload)
        self.prompts: list[str] = []

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        self.prompts.append(prompt)
        return self._raw


class _FakePodRepo:
    def __init__(self, existing: list[Pod] | None = None) -> None:
        self.saved: list[Pod] = []
        self._existing = existing or []

    async def get(self, pid: PodId) -> Pod | None:
        for pod in [*self._existing, *self.saved]:
            if pod.id == pid:
                return pod
        return None

    async def list_for_user(self, uid: UserId) -> list[Pod]:
        return [p for p in [*self._existing, *self.saved] if p.owner_id == uid]

    async def save(self, p: Pod) -> Pod:
        self.saved.append(p)
        return p

    async def delete(self, pid: PodId) -> None: ...


class _FakeCharacterRepo:
    def __init__(self) -> None:
        self.saved: list[Character] = []

    async def get(self, cid: CharacterId) -> Character | None:
        return None

    async def list_for_pod(self, pod_id: PodId) -> list[Character]:
        return [c for c in self.saved if c.pod_id == pod_id]

    async def save(self, c: Character) -> Character:
        self.saved.append(c)
        return c

    async def delete(self, cid: CharacterId) -> None: ...


class _FakeTopicRepo:
    def __init__(self) -> None:
        self.saved: list[Topic] = []

    async def get(self, tid: TopicId) -> Topic | None:
        return None

    async def list_for_pod(self, pod_id: PodId) -> list[Topic]:
        return [t for t in self.saved if t.pod_id == pod_id]

    async def save(self, t: Topic) -> Topic:
        self.saved.append(t)
        return t

    async def delete(self, tid: TopicId) -> None: ...


# ============================================================================
# Builders
# ============================================================================
def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "series_name": "Curiosos del Cosmos",
        "bible": {
            "genre": "edutainment",
            "audience": "kids",
            "tone": "wonder",
            "narrative_arc": "a curious kid explores one space mystery per episode",
            "format": "2-3 min explainer",
        },
        "style_profile": "kids_3d",
        "art_style": "soft 3D, pastel palette",
        "characters": [
            {
                "name": "Nova", "role": "lead",
                "personality": "curious", "look_description": "girl, space suit",
            },
            {"name": "Orbi", "role": "sidekick", "personality": "witty robot"},
            {"name": "Prof. Lux", "role": "mentor"},
        ],
        "topics": [
            "Why is the sky dark at night?",
            "What is a black hole?",
            "Why is the sky dark at night?",  # dup → deduped
        ],
    }
    base.update(overrides)
    return base


def _blueprint() -> PodBlueprint:
    return PodBlueprint(
        series_name="Curiosos del Cosmos",
        bible=SeriesBible(genre="edutainment", audience="kids", tone="wonder"),
        style_profile=StyleProfile.KIDS_3D,
        art_style="soft 3D",
        characters=(
            CharacterBlueprint(name="Nova", role="lead", personality="curious"),
            CharacterBlueprint(name="Orbi", role="sidekick"),
        ),
        topic_seeds=("What is a black hole?", "Why do stars twinkle?"),
    )


# ============================================================================
# DraftPodBlueprint
# ============================================================================
async def test_draft_parses_blueprint() -> None:
    # Arrange
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]

    # Act
    bp = await uc.execute(idea="space for kids", language="es")

    # Assert — fields parsed, style mapped, topics deduped
    assert bp.series_name == "Curiosos del Cosmos"
    assert bp.bible.genre == "edutainment"
    assert bp.bible.language == "es"  # taken from the request, not the LLM
    assert bp.style_profile is StyleProfile.KIDS_3D
    assert len(bp.characters) == 3
    assert bp.characters[0].name == "Nova"
    assert bp.topic_seeds == ("Why is the sky dark at night?", "What is a black hole?")


async def test_draft_coerces_unknown_style_to_default() -> None:
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload(style_profile="hand_drawn_surrealism")))  # type: ignore[arg-type]
    bp = await uc.execute(idea="something arty")
    assert bp.style_profile is StyleProfile.CINEMATIC_3D


async def test_draft_caps_characters_and_topics() -> None:
    # Arrange — LLM offers 3 characters / 3 topics, caller wants fewer
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]

    # Act
    bp = await uc.execute(idea="space", character_count=2, topic_count=1)

    # Assert
    assert len(bp.characters) == 2
    assert len(bp.topic_seeds) == 1


async def test_draft_rejects_blank_idea() -> None:
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        await uc.execute(idea="   ")


async def test_draft_raises_on_invalid_json() -> None:
    uc = DraftPodBlueprint(llm=_FakeLLM("not-json"))  # type: ignore[arg-type]
    with pytest.raises(ProviderError, match="invalid JSON"):
        await uc.execute(idea="space")


async def test_draft_falls_back_to_idea_when_series_name_missing() -> None:
    payload = _payload()
    del payload["series_name"]
    uc = DraftPodBlueprint(llm=_FakeLLM(payload))  # type: ignore[arg-type]
    bp = await uc.execute(idea="Aventuras submarinas")
    assert bp.series_name == "Aventuras submarinas"


# ============================================================================
# CreatePodFromBlueprint
# ============================================================================
async def test_create_pod_persists_pod_characters_and_topics() -> None:
    # Arrange
    pod_repo = _FakePodRepo()
    char_repo = _FakeCharacterRepo()
    topic_repo = _FakeTopicRepo()
    uc = CreatePodFromBlueprint(pod_repo, char_repo, topic_repo)  # type: ignore[arg-type]

    # Act
    pod = await uc.execute(owner_id=OWNER, name="cosmos", blueprint=_blueprint())

    # Assert — pod config derived from the bible; children scoped to the pod
    assert pod.owner_id == OWNER
    assert pod.config.series_name == "Curiosos del Cosmos"
    assert pod.config.style_profile is StyleProfile.KIDS_3D
    assert pod.config.target_audience == "kids"
    assert "Genre: edutainment" in (pod.config.series_context or "")
    assert [c.name for c in char_repo.saved] == ["Nova", "Orbi"]
    assert all(c.pod_id == pod.id for c in char_repo.saved)
    assert [t.title for t in topic_repo.saved] == [
        "What is a black hole?", "Why do stars twinkle?",
    ]
    assert all(t.pod_id == pod.id for t in topic_repo.saved)


async def test_create_pod_rejects_duplicate_name() -> None:
    # Arrange — a pod with the same name already exists for this user
    existing = Pod(
        id=PodId("pod_existing"),
        owner_id=OWNER,
        name="cosmos",
        config=PodConfig(series_name="X"),
    )
    pod_repo = _FakePodRepo(existing=[existing])
    uc = CreatePodFromBlueprint(pod_repo, _FakeCharacterRepo(), _FakeTopicRepo())  # type: ignore[arg-type]

    # Act / Assert
    with pytest.raises(ConflictError):
        await uc.execute(owner_id=OWNER, name="cosmos", blueprint=_blueprint())


# ============================================================================
# Content taxonomy (Fase 8 — wizard content types)
# ============================================================================
def test_content_profile_story_uses_reference_characters_and_arc() -> None:
    p = content_profile(ContentType.STORY)
    assert p.duration_strategy is DurationStrategy.ARC
    assert p.generation_mode is GenerationMode.SYNTHETIC
    assert p.default_character_mode is CharacterMode.REFERENCE
    assert not p.llm_decides_length


def test_content_profile_recreation_is_v2v_scene_native() -> None:
    p = content_profile(ContentType.SCENE_RECREATION)
    assert p.generation_mode is GenerationMode.VIDEO_TO_VIDEO
    assert p.default_character_mode is CharacterMode.SCENE_NATIVE
    assert p.allowed_character_modes == (CharacterMode.SCENE_NATIVE,)


def test_content_profile_educational_lets_llm_size_length() -> None:
    p = content_profile(ContentType.EDUCATIONAL)
    assert p.llm_decides_length
    assert CharacterMode.NARRATOR_PIP in p.allowed_character_modes
    assert p.default_character_mode is CharacterMode.NONE


async def test_draft_meme_omits_characters_and_uses_short_duration() -> None:
    # Meme default char mode is OPTIONAL → characters requested but format-light;
    # here the LLM returned characters but duration must follow the meme profile.
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]
    bp = await uc.execute(idea="gatos graciosos", content_type=ContentType.MEME)
    assert bp.content_type is ContentType.MEME
    assert bp.duration_seconds == 20
    assert bp.interactive_questions == 0


async def test_draft_educational_keeps_volunteered_characters() -> None:
    # Educational defaults to CharacterMode.NONE, but it never *forces* chars.
    # If the LLM volunteers characters, the wizard keeps them and upgrades the
    # mode to OPTIONAL so they aren't thrown away and the UI can edit them.
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]
    bp = await uc.execute(idea="historia de Roma", content_type=ContentType.EDUCATIONAL)
    assert len(bp.characters) == 3
    assert bp.character_mode is CharacterMode.OPTIONAL
    assert bp.duration_seconds == 90


async def test_draft_educational_without_characters_stays_none() -> None:
    # When the LLM returns no characters, educational stays NONE + empty.
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload(characters=[])))  # type: ignore[arg-type]
    bp = await uc.execute(idea="historia de Roma", content_type=ContentType.EDUCATIONAL)
    assert bp.characters == ()
    assert bp.character_mode is CharacterMode.NONE
    assert bp.duration_seconds == 90


async def test_draft_story_enables_audience_questions() -> None:
    uc = DraftPodBlueprint(llm=_FakeLLM(_payload()))  # type: ignore[arg-type]
    bp = await uc.execute(idea="cuentos", content_type=ContentType.STORY)
    assert bp.interactive_questions == 2
    assert bp.character_mode is CharacterMode.REFERENCE
    assert len(bp.characters) == 3


async def test_create_pod_persists_content_taxonomy() -> None:
    pod_repo = _FakePodRepo()
    uc = CreatePodFromBlueprint(pod_repo, _FakeCharacterRepo(), _FakeTopicRepo())  # type: ignore[arg-type]
    bp = _blueprint().model_copy(update={
        "content_type": ContentType.EDUCATIONAL,
        "character_mode": CharacterMode.NARRATOR_PIP,
        "duration_seconds": 75,
        "max_clip_seconds": 10,
        "interactive_questions": 1,
    })
    pod = await uc.execute(owner_id=OWNER, name="edu", blueprint=bp)
    assert pod.config.content_type is ContentType.EDUCATIONAL
    assert pod.config.character_mode is CharacterMode.NARRATOR_PIP
    assert pod.config.duration_seconds == 75
    assert pod.config.max_clip_seconds == 10
    assert pod.config.interactive_questions == 1


# ============================================================================
# SeriesBible behavior
# ============================================================================
def test_bible_as_context_includes_set_fields_only() -> None:
    bible = SeriesBible(genre="edutainment", audience="kids", tone="wonder")
    ctx = bible.as_context()
    assert "Genre: edutainment." in ctx
    assert "Audience: kids." in ctx
    assert "Tone: wonder." in ctx
    assert "Arc:" not in ctx  # narrative_arc unset → omitted
