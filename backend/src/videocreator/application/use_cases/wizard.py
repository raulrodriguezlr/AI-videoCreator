"""AI Pod Wizard use cases (Plan Maestro §B.5).

Turns a vague series idea into a reviewable `PodBlueprint` via the LLM, then —
after the user edits/approves it — materializes the blueprint into a real Pod
with its characters and seed topics.

Design note: this first cut is intentionally *stateless*. `DraftPodBlueprint`
persists nothing and hands the blueprint back for the client to edit;
`CreatePodFromBlueprint` commits the approved result in one shot. The Plan
Maestro's resumable `WizardSession` (per-step jobs, golden-prompt evals) is a
later, cloud-oriented layer — the draft→confirm split already delivers the core
"idea in, pod out" value without that machinery, and keeps everything testable
with a single fake LLM call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Character, Pod, PodConfig, Topic
from videocreator.domain.ports import (
    CharacterRepository,
    LLMPort,
    PodRepository,
    TopicRepository,
)
from videocreator.domain.value_objects import (
    CharacterBlueprint,
    CharacterMode,
    ContentType,
    NarrationStyle,
    PodBlueprint,
    SeriesBible,
    SettingMode,
    StyleProfile,
    TopicStatus,
    content_profile,
)
from videocreator.shared.errors import ConflictError, ProviderError, ValidationError
from videocreator.shared.ids import (
    UserId,
    new_character_id,
    new_pod_id,
    new_topic_id,
)

_BLUEPRINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "series_name": {"type": "string"},
        "bible": {
            "type": "object",
            "properties": {
                "genre": {"type": "string"},
                "audience": {"type": "string"},
                "tone": {"type": "string"},
                "narrative_arc": {"type": "string"},
                "format": {"type": "string"},
            },
            "required": ["genre"],
        },
        "style_profile": {
            "type": "string",
            "enum": [profile.value for profile in StyleProfile],
        },
        "art_style": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "personality": {"type": "string"},
                    "look_description": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["series_name", "bible", "characters", "topics"],
}


def _opt(value: object) -> str | None:
    """Coerce an optional LLM string field to a trimmed value or None."""
    text = str(value or "").strip()
    return text or None


def _coerce_style(raw: object) -> StyleProfile:
    """Map a free-text style suggestion to the nearest `StyleProfile`.

    Falls back to the cinematic default rather than failing — the user can
    override the choice when reviewing the blueprint.
    """
    text = str(raw or "").strip().lower()
    for profile in StyleProfile:
        if profile.value == text:
            return profile
    return StyleProfile.CINEMATIC_3D


def _parse_bible(raw: object, *, language: str) -> SeriesBible:
    data = raw if isinstance(raw, dict) else {}
    return SeriesBible(
        genre=str(data.get("genre") or "general").strip() or "general",
        audience=str(data.get("audience") or "general").strip() or "general",
        tone=_opt(data.get("tone")),
        narrative_arc=_opt(data.get("narrative_arc")),
        format=_opt(data.get("format")),
        language=language,
    )


def _parse_characters(raw: object, *, limit: int) -> tuple[CharacterBlueprint, ...]:
    out: list[CharacterBlueprint] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append(
                CharacterBlueprint(
                    name=name,
                    role=str(item.get("role") or "supporting").strip() or "supporting",
                    personality=_opt(item.get("personality")),
                    look_description=_opt(item.get("look_description")),
                )
            )
            if len(out) >= limit:
                break
    return tuple(out)


def _parse_topics(raw: object, *, limit: int) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
            if len(out) >= limit:
                break
    return tuple(out)


# Per-content-type creative guidance injected into the wizard prompt so the
# blueprint matches the format's conventions (length, character needs, pacing).
_CONTENT_GUIDANCE: dict[ContentType, str] = {
    ContentType.STORY: (
        "FORMAT: episodic narrative series. Each episode tells a self-contained "
        "story with a clear arc and recurring characters who need consistent "
        "looks (reference images will be generated from look_description)."
    ),
    ContentType.MEME: (
        "FORMAT: short, punchy viral humor (meme-length). Topics are quick comedic "
        "premises or relatable gags. Characters are OPTIONAL — only invent them if "
        "the humor needs a recurring mascot; otherwise return an empty characters "
        "list."
    ),
    ContentType.SCENE_RECREATION: (
        "FORMAT: recreations of famous movie/series scenes with a twist (the source "
        "video is modified, video-to-video). Do NOT invent character reference "
        "looks — the characters come from the source footage. Topics name the scene "
        "to recreate and the twist to apply. Return an empty characters list."
    ),
    ContentType.EDUCATIONAL: (
        "FORMAT: educational / divulgation. Each episode explains a topic; its "
        "length should fit the topic (the script generator decides how long). "
        "Characters are usually NOT needed — return an empty characters list unless "
        "a single recurring narrator/host clearly helps."
    ),
    ContentType.OTHER: (
        "FORMAT: custom concept described by the user. Infer the most fitting "
        "structure, length and whether characters are needed from the idea."
    ),
}


def _render_wizard_prompt(
    *, idea: str, language: str, character_count: int, topic_count: int,
    content_type: ContentType, wants_characters: bool,
) -> str:
    guidance = _CONTENT_GUIDANCE[content_type]
    if wants_characters:
        char_line = (
            f"- exactly {character_count} distinct main characters "
            "(name, role, personality, look_description),\n"
        )
    else:
        char_line = (
            "- characters: return an EMPTY list unless the format clearly needs a "
            "recurring figure (see FORMAT note),\n"
        )
    return (
        "You are a creative producer designing a new short-form video series "
        "from a rough idea.\n\n"
        f"{guidance}\n\n"
        f"Idea: {idea.strip()}\n"
        f"Output language: {language}.\n\n"
        "Produce a complete series blueprint:\n"
        "- a memorable series_name,\n"
        "- a bible (genre, target audience, tone, narrative_arc, format),\n"
        "- a style_profile chosen from the allowed enum,\n"
        "- a short art_style description,\n"
        f"{char_line}"
        f"- {topic_count} fresh episode topic ideas with continuity.\n"
        "Return strict JSON matching the supplied schema."
    )


def _render_enhance_prompt(*, idea: str, language: str) -> str:
    return (
        "You are a world-class creative director, showrunner and storyteller for "
        "short-form educational/entertainment video. Rewrite the user's rough series "
        "idea into a vivid, specific and production-ready creative brief: sharpen the "
        "hook and premise, define the audience and tone, hint at recurring characters "
        "and a visual style, and suggest the kind of episodes it could run.\n\n"
        f"Output language: {language}.\n\n"
        f"Rough idea:\n{idea.strip()}\n\n"
        "Return ONLY the improved brief as plain prose (2-4 short paragraphs). "
        "No headings, no bullet lists, no preamble."
    )


@dataclass(frozen=True, slots=True)
class EnhanceIdea:
    """Polish a rough pod idea into a richer brief before drafting a blueprint.

    Returns free prose (not JSON) so the user can read, tweak and feed it back
    into `DraftPodBlueprint` — an optional "make it better" step in the wizard.
    """

    llm: LLMPort

    async def execute(self, *, idea: str, language: str = "es") -> str:
        if not idea.strip():
            raise ValidationError("idea must not be empty")
        text = await self.llm.complete(
            _render_enhance_prompt(idea=idea, language=language), temperature=0.8,
        )
        return text.strip()


@dataclass(frozen=True, slots=True)
class DraftPodBlueprint:
    """Step 1 — turn a vague idea into a structured, editable `PodBlueprint`."""

    llm: LLMPort

    async def execute(
        self,
        *,
        idea: str,
        language: str = "es",
        character_count: int = 3,
        topic_count: int = 5,
        content_type: ContentType = ContentType.STORY,
        character_mode: CharacterMode | None = None,
        narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL,
        setting_mode: SettingMode = SettingMode.IN_SCENE,
    ) -> PodBlueprint:
        if not idea.strip():
            raise ValidationError("idea must not be empty")

        # Resolve the type's behavior bundle (duration sizing, char strategy).
        profile = content_profile(content_type)
        char_mode = character_mode or profile.default_character_mode
        wants_characters = char_mode in (
            CharacterMode.REFERENCE, CharacterMode.OPTIONAL, CharacterMode.NARRATOR_PIP
        )

        prompt = _render_wizard_prompt(
            idea=idea,
            language=language,
            character_count=character_count,
            topic_count=topic_count,
            content_type=content_type,
            wants_characters=wants_characters,
        )
        raw = await self.llm.complete(
            prompt, response_schema=_BLUEPRINT_SCHEMA, temperature=0.9,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        bible = _parse_bible(data.get("bible"), language=language)
        # Parse characters regardless of wants_characters, because the prompt allows
        # the LLM to return a character if it's "clearly needed" (like a narrator).
        characters = _parse_characters(data.get("characters"), limit=character_count)

        # If the LLM returned characters but the default mode was NONE, upgrade the mode
        # so the characters aren't thrown away and the UI allows editing them.
        if characters and char_mode == CharacterMode.NONE:
            char_mode = CharacterMode.OPTIONAL

        # If the mode is STILL none (no characters generated), enforce empty tuple.
        if char_mode == CharacterMode.NONE:
            characters = ()

        return PodBlueprint(
            series_name=str(data.get("series_name") or idea.strip()).strip(),
            bible=bible,
            style_profile=_coerce_style(data.get("style_profile")),
            art_style=_opt(data.get("art_style")),
            characters=characters,
            topic_seeds=_parse_topics(data.get("topics"), limit=topic_count),
            content_type=content_type,
            character_mode=char_mode,
            duration_seconds=profile.default_duration_s,
            max_clip_seconds=profile.default_max_clip_s,
            # Kids-ish stories invite audience questions; other formats default off.
            interactive_questions=2 if content_type == ContentType.STORY else 0,
            narration_style=narration_style,
            setting_mode=setting_mode,
        )


@dataclass(frozen=True, slots=True)
class CreatePodFromBlueprint:
    """Step 2 — materialize an approved blueprint into a persisted pod."""

    pod_repo: PodRepository
    char_repo: CharacterRepository
    topic_repo: TopicRepository

    async def execute(
        self, *, owner_id: UserId, name: str, blueprint: PodBlueprint,
    ) -> Pod:
        existing = await self.pod_repo.list_for_user(owner_id)
        if any(p.name == name for p in existing):
            raise ConflictError(f"pod with name '{name}' already exists")

        config = PodConfig(
            series_name=blueprint.series_name,
            target_audience=blueprint.bible.audience,
            language=blueprint.bible.language,
            art_style=blueprint.art_style,
            style_profile=blueprint.style_profile,
            series_context=blueprint.bible.as_context(),
            content_type=blueprint.content_type,
            character_mode=blueprint.character_mode,
            duration_seconds=blueprint.duration_seconds,
            max_clip_seconds=blueprint.max_clip_seconds,
            interactive_questions=blueprint.interactive_questions,
            narration_style=blueprint.narration_style,
            setting_mode=blueprint.setting_mode,
        )
        pod = await self.pod_repo.save(
            Pod(id=new_pod_id(), owner_id=owner_id, name=name, config=config)
        )

        for index, character in enumerate(blueprint.characters):
            await self.char_repo.save(
                Character(
                    id=new_character_id(),
                    pod_id=pod.id,
                    name=character.name,
                    role=character.role or ("lead" if index == 0 else "supporting"),
                    personality=character.personality,
                    look_description=character.look_description,
                )
            )

        for seed in blueprint.topic_seeds:
            await self.topic_repo.save(
                Topic(
                    id=new_topic_id(),
                    pod_id=pod.id,
                    title=seed,
                    status=TopicStatus.PENDING,
                )
            )
        return pod


__all__ = ["CreatePodFromBlueprint", "DraftPodBlueprint", "EnhanceIdea"]
