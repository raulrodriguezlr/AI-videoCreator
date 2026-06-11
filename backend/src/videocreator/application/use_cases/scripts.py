"""Script generation use case.

Renders a Gemini-compatible JSON schema for scenes with full cinematographic
metadata (camera, mood, lighting, transitions) and persists the resulting Script
entity. The prompt injects the universal video_rules (transitions, lip-sync,
camera vocabulary) so the LLM generates production-quality scene metadata that
the render engine can translate into specific provider instructions.

Architecture Note
-----------------
The video rules are embedded as a formatted string constant rather than loaded
from ``pods/video_rules.json`` at runtime. This keeps the application layer free
of filesystem dependencies (Clean Architecture: use-cases depend only on ports).
The rules are universal and rarely change; if they do, update ``_VIDEO_RULES``.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Character, Scene, Script
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    LLMPort,
    PodRepository,
    ScriptRepository,
    TopicRepository,
)
from videocreator.shared.errors import (
    ConflictError,
    ForbiddenError,
    PodNotFound,
    ProviderError,
    ScriptNotFound,
)
from videocreator.shared.ids import (
    PodId,
    SceneId,
    ScriptId,
    TopicId,
    UserId,
    new_scene_id,
    new_script_id,
)


# ---------------------------------------------------------------------------
# Video rules — camera vocabulary + transition semantics + guard rails
# (Legacy: PromptManager.load_video_rules() read pods/video_rules.json)
# ---------------------------------------------------------------------------
_VIDEO_RULES = """\
## VIDEO PRODUCTION RULES (MANDATORY)

### TRANSITIONS (transition_to_next)
- **continue** — Fluid static continuation. ONLY for prolonging static dialogue \
or a slow pan over an empty landscape. visual_prompt MUST be exactly the same as \
the previous scene. If there is physical movement, pose change, or new objects, \
use 'cut'.
- **cut** — Small cut. Change of angle/shot within the same scene. Action or \
dialogue continues from another viewpoint. This is the MAIN transition to use.
- **scene_change** — Large cut. Complete change of location or action. A \
completely new situation begins.

GOLDEN RULE: NEVER ask a character to perform more than ONE main physical action \
per scene. Divide actions using 'cut'. NEVER introduce a sudden scene change or \
new character WITHIN a single clip.
ANTI-MORPHING RULE: NEVER use 'continue' for moving actions. It causes severe \
morphing during pose/camera changes. When in doubt, ALWAYS use 'cut'.
FORBIDDEN transition value: 'extend'.

### LIP-SYNC RULES (CRITICAL)
- ABSOLUTELY FORBIDDEN: Do NOT write 'The squirrel says ...', 'The character \
says ...' or ANY 'X says "..."' pattern inside visual_prompt.
- visual_prompt contains ONLY physical descriptions: actions, environment, \
expressions, poses. ZERO dialogue text.
- All spoken dialogue goes EXCLUSIVELY in the audio_text field.
- When a character speaks, prefer 'close-up' or 'medium' shots.

### VISUAL CONTINUITY
- ALWAYS describe the full physical appearance of characters in every \
visual_prompt (clothing, colors, accessories).
- ABSOLUTELY PROHIBITED to include text, subtitles, watermarks, or any \
written content in visual_prompt. Always append: 'absolutely no text, \
no subtitles, no letters, no watermarks, no written words'.
- visual_prompt MUST be in ENGLISH.
- Always prefix visual_prompt with the art style.
- DO NOT use contradictory visual concepts (e.g., 'crystal acorn').

### PROP CONTINUITY
- If a character holds an object in consecutive scenes, describe it in BOTH \
visual_prompts using the EXACT SAME WORDS.
- Objects cannot magically appear or disappear. Show the action with a 'cut'.

### CAMERA OPTIONS (choose from these ONLY)
shot_type: wide | medium | close-up | extreme_close_up | aerial | over_the_shoulder
movement: static | pan_left | pan_right | tracking | dolly_in | dolly_out | crane_up
angle: eye_level | low_angle | high_angle | bird_eye | dutch_angle

### MOOD OPTIONS
warm | tense | joyful | mysterious | triumphant | calm | exciting

### LIGHTING OPTIONS
golden_hour | soft_diffused | dramatic_shadows | bright_daylight | moonlit

### PACING GUIDELINES
- 4-5 seconds: Fast cuts, reactions, visual transitions.
- 6-7 seconds: Short dialogue, simple action, exploration.
- 8 seconds: Establishing scenes, emotional climax, important moments.
"""

# ---------------------------------------------------------------------------
# JSON schema the LLM must fill — matches the legacy output_format
# ---------------------------------------------------------------------------
_SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        # Educational lesson of the episode (for memory + SEO copy)
        "moral": {"type": "string"},
        # Ambient music prompt describing the overall episode mood
        "ambient_audio_prompt": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scene_number": {"type": "integer"},
                    "narrative_phase": {
                        "type": "string",
                        "enum": [
                            "introduction", "establishing", "rising_action",
                            "climax", "falling_action", "resolution", "transition",
                        ],
                    },
                    "visual_prompt": {"type": "string"},
                    "audio_text": {"type": "string"},
                    "character": {"type": "string"},
                    "voice_direction": {"type": "string"},
                    "camera": {
                        "type": "object",
                        "properties": {
                            "shot_type": {
                                "type": "string",
                                "enum": [
                                    "wide", "medium", "close-up",
                                    "extreme_close_up", "aerial",
                                    "over_the_shoulder",
                                ],
                            },
                            "movement": {
                                "type": "string",
                                "enum": [
                                    "static", "pan_left", "pan_right",
                                    "tracking", "dolly_in", "dolly_out",
                                    "crane_up",
                                ],
                            },
                            "angle": {
                                "type": "string",
                                "enum": [
                                    "eye_level", "low_angle", "high_angle",
                                    "bird_eye", "dutch_angle",
                                ],
                            },
                        },
                        "required": ["shot_type", "movement", "angle"],
                    },
                    "mood": {
                        "type": "string",
                        "enum": [
                            "warm", "tense", "joyful", "mysterious",
                            "triumphant", "calm", "exciting",
                        ],
                    },
                    "lighting": {
                        "type": "string",
                        "enum": [
                            "golden_hour", "soft_diffused",
                            "dramatic_shadows", "bright_daylight", "moonlit",
                        ],
                    },
                    "transition_to_next": {
                        "type": "string",
                        "enum": ["continue", "cut", "scene_change"],
                    },
                    "duration_seconds": {"type": "number"},
                },
                "required": [
                    "visual_prompt", "audio_text", "camera",
                    "mood", "lighting", "transition_to_next",
                    "duration_seconds",
                ],
            },
        },
    },
    "required": ["title", "scenes"],
}


def _format_characters(characters: list[Character]) -> str:
    """Format character info for the LLM prompt so it can assign `character` fields."""
    if not characters:
        return "(no characters defined — use 'Narrator' as the default character)"
    lines: list[str] = []
    for c in characters:
        parts = [f"- **{c.name}**"]
        if c.role:
            parts.append(f"(role: {c.role})")
        if c.personality:
            parts.append(f"— {c.personality}")
        if c.look_description:
            parts.append(f"[look: {c.look_description}]")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _scene_count_targets(
    target_duration_s: int, max_clip_seconds: int = 8
) -> tuple[int, int]:
    """Minimum and typical scene counts needed to fill the target duration.

    Scenes run from ~4s up to ``max_clip_seconds`` (regression #5: this ceiling
    used to be hardcoded at 8). ``min_scenes`` uses the ceiling so that even if
    the LLM picks the longest allowed scene length, the episode still reaches the
    target; ``typical`` assumes a comfortable ~75% of the ceiling for a healthy
    buffer above it.
    """
    ceiling = max(1, max_clip_seconds)
    typical_len = max(1, round(ceiling * 0.75))         # e.g. 8 -> 6, 10 -> 8
    min_scenes = max(1, -(-target_duration_s // ceiling))      # ceil(/ceiling)
    typical = max(min_scenes, -(-target_duration_s // typical_len))  # ceil(/typical_len)
    return min_scenes, typical


def _interactive_block(count: int) -> str:
    """Instruction block asking the LLM to address the audience directly.

    Restores the legacy ``num_interactive_questions`` behavior (regression #1):
    when ``count`` > 0 the script weaves that many direct questions to the viewer
    into the dialogue at natural beats. Empty string when disabled.
    """
    if count <= 0:
        return ""
    return (
        f"\n## AUDIENCE INTERACTION (MANDATORY)\n"
        f"Weave EXACTLY {count} direct question(s) to the audience into the "
        f"`audio_text` at natural narrative beats (e.g. before the climax or a "
        f"decision). Make them engaging and answerable by the target audience "
        f"(e.g. '¿Qué creéis que hará a continuación?'). Spread them out — do not "
        f"cluster them in one scene.\n"
    )


def _render_script_prompt(
    *, series_name: str, language: str, target_duration_s: int,
    topic_title: str, topic_description: str | None,
    series_context: str | None, art_style: str | None,
    characters: list[Character],
    episode_memory: str | None = None,
    max_clip_seconds: int = 8,
    interactive_questions: int = 0,
) -> str:
    """Build the full script-generation prompt with video rules and camera vocabulary.

    This restores the legacy 5-layer camera pipeline: the video rules inject the
    closed camera vocabulary, the schema enforces it, and the prompt tells the LLM
    to use it narratively.
    """
    ctx = series_context.strip() if series_context else "(no extra context)"
    desc = topic_description.strip() if topic_description else "(no description)"
    style = art_style or "3D animation"
    min_scenes, typical_scenes = _scene_count_targets(target_duration_s, max_clip_seconds)
    char_block = _format_characters(characters)
    if episode_memory and episode_memory.strip():
        memory_block = (
            f"\n## PREVIOUS EPISODES (maintain continuity — reference them when natural)\n"
            f"{episode_memory.strip()}\n"
            f"If this episode's TOPIC is a callback or sequel to one listed above, "
            f"honor that connection explicitly in the story (regression #3).\n"
        )
    else:
        memory_block = (
            "\n## PREVIOUS EPISODES\n"
            "This is the first episode of the series. No prior history.\n"
        )

    return (
        f"You are the head director and screenwriter for '{series_name}', "
        f"with Pixar/Disney cinematic experience. Generate a strict JSON "
        f"cinematic script ready for Generative AI video models.\n"
        f"Provide physical visual prompts in ENGLISH and audio dialogues in "
        f"{language}.\n\n"
        f"## SERIES CONTEXT\n{ctx}\n"
        f"{memory_block}\n"
        f"## CHARACTERS\n{char_block}\n\n"
        f"## TOPIC\n{topic_title}\n{desc}\n\n"
        f"## ART STYLE\n{style}\n"
        f"Every visual_prompt MUST start with this art style prefix.\n\n"
        f"## DURATION (STRICT — NON-NEGOTIABLE)\n"
        f"- The episode MUST total AT LEAST {target_duration_s} seconds of video.\n"
        f"- Produce BETWEEN {min_scenes} AND {typical_scenes} scenes, each 4-"
        f"{max_clip_seconds} seconds long ({typical_scenes} is the ideal count).\n"
        f"- The SUM of every scene's `duration_seconds` MUST be >= "
        f"{target_duration_s}.\n"
        f"- No single scene may exceed {max_clip_seconds} seconds.\n"
        f"- A script with fewer scenes that does not reach {target_duration_s}s "
        f"is INVALID. Do NOT compress the story into a handful of long scenes — "
        f"tell it across MANY short, dynamic scenes.\n"
        f"- Each scene needs a vivid visual_prompt and audio_text.\n\n"
        f"## MANDATORY NARRATIVE STRUCTURE\n"
        f"Scenes MUST progress through: introduction -> establishing -> "
        f"rising_action -> climax -> falling_action -> resolution.\n"
        f"{_interactive_block(interactive_questions)}\n"
        f"{_VIDEO_RULES}\n\n"
        f"## CAMERA DIRECTION (MANDATORY)\n"
        f"You MUST fill camera.shot_type, camera.movement, and camera.angle "
        f"for EVERY scene. Vary them narratively:\n"
        f"- Use wide/aerial for establishing shots\n"
        f"- Use close-up for emotional moments and dialogue\n"
        f"- Use tracking/dolly_in for action sequences\n"
        f"- Match the camera to the mood and narrative_phase\n\n"
        f"## MOOD & LIGHTING (MANDATORY)\n"
        f"Set mood and lighting for every scene to create cinematic atmosphere.\n\n"
        f"## TRANSITIONS (MANDATORY)\n"
        f"Set transition_to_next for every scene. Read the transition rules above "
        f"carefully — 'cut' is the main transition, 'continue' only for static.\n\n"
        f"## EXTRA FIELDS (required at the top level of your JSON)\n"
        f"- `moral`: one sentence — the lesson or value the episode teaches.\n"
        f"- `ambient_audio_prompt`: short English music prompt describing the "
        f"episode's overall ambient mood (e.g. 'soft orchestral adventure music "
        f"with gentle woodwinds, warm and uplifting').\n\n"
        f"Return strict JSON matching the supplied schema."
    )


def _to_scene(idx: int, raw: dict[str, Any]) -> Scene:
    """Parse a single scene from the LLM output into a domain Scene.

    Extracts the domain-level fields for the UI AND stores the full raw dict
    so the render engine receives camera, mood, lighting, character, and
    voice_direction — the fields that make the video cinematographic.
    """
    # Transition: legacy uses 'transition_to_next', fallback to 'transition'
    transition_raw = raw.get("transition_to_next") or raw.get("transition", "cut")
    transition = transition_raw if transition_raw in {"cut", "continue", "scene_change"} else "cut"

    # Camera: legacy nests under 'camera' object, current uses flat fields
    camera = raw.get("camera") or {}
    camera_shot = camera.get("shot_type") or raw.get("camera_shot")
    camera_movement = camera.get("movement") or raw.get("camera_movement")
    camera_angle = camera.get("angle") or raw.get("camera_angle")

    # Duration: legacy uses 'duration_seconds', current uses 'duration_s'
    duration = float(raw.get("duration_seconds") or raw.get("duration_s", 8.0))

    sid: SceneId = new_scene_id()
    return Scene(
        id=sid,
        index=idx,
        visual_prompt=str(raw["visual_prompt"]),
        audio_text=raw.get("audio_text"),
        transition=transition,  # type: ignore[arg-type]
        duration_s=duration,
        camera_shot=camera_shot,
        camera_movement=camera_movement,
        camera_angle=camera_angle,
        # Store the FULL raw dict — the render engine reads character,
        # voice_direction, mood, lighting, narrative_phase, camera object
        # directly from here via _scene_to_engine().
        raw=dict(raw),
    )


@dataclass(frozen=True, slots=True)
class GenerateScript:
    pod_repo: PodRepository
    topic_repo: TopicRepository
    script_repo: ScriptRepository
    character_repo: CharacterRepository
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

        characters = await self.character_repo.list_for_pod(pod_id)

        prompt = _render_script_prompt(
            series_name=pod.config.series_name,
            language=pod.config.language,
            target_duration_s=pod.config.duration_seconds,
            topic_title=topic.title,
            topic_description=topic.description,
            series_context=pod.config.series_context,
            art_style=pod.config.art_style,
            characters=characters,
            episode_memory=pod.config.universe_memory,
            max_clip_seconds=pod.config.max_clip_seconds,
            interactive_questions=pod.config.interactive_questions,
        )
        # Enforce the minimum scene count at the schema level too — Gemini honours
        # `minItems`, so this is a hard floor on top of the prompt's instruction.
        min_scenes, _ = _scene_count_targets(
            pod.config.duration_seconds, pod.config.max_clip_seconds
        )
        schema = copy.deepcopy(_SCENE_SCHEMA)
        schema["properties"]["scenes"]["minItems"] = min_scenes
        raw = await self.llm.complete(prompt, response_schema=schema, temperature=0.8)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        scenes = [_to_scene(i, s) for i, s in enumerate(data.get("scenes") or [])
                  if isinstance(s, dict) and "visual_prompt" in s]
        script_id: ScriptId = new_script_id()
        title = str(data.get("title") or topic.title)
        summary = data.get("summary")
        moral = data.get("moral")
        ambient_audio_prompt = data.get("ambient_audio_prompt")
        script = Script(
            id=script_id,
            pod_id=pod_id,
            topic_id=topic_id,
            title=title,
            summary=summary,
            moral=moral,
            ambient_audio_prompt=ambient_audio_prompt,
            scenes=scenes,
        )
        saved = await self.script_repo.save(script)

        # Update universe_memory — append this episode's entry so future
        # scripts can reference it for narrative continuity.
        if title or summary or moral:
            entry = f"- \"{title}\""
            if summary:
                entry += f": {summary[:120].rstrip()}"
            if moral:
                entry += f" [moral: {moral[:80].rstrip()}]"
            existing_memory = pod.config.universe_memory or ""
            # Keep the last ~10 entries (trim from the top if too long).
            lines = [l for l in existing_memory.splitlines() if l.strip()]
            lines.append(entry)
            lines = lines[-10:]
            updated_config = pod.config.model_copy(
                update={"universe_memory": "\n".join(lines)}
            )
            await self.pod_repo.save(pod.model_copy(update={"config": updated_config}))

        return saved


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


@dataclass(frozen=True, slots=True)
class DeleteScript:
    """Delete a script, refusing if any episode still references it.

    Deleting a script that an episode points at would orphan that episode's
    `script_id`, so the use case raises `ConflictError` instead — the caller
    must delete (or repoint) the dependent episode(s) first.
    """

    pod_repo: PodRepository
    script_repo: ScriptRepository
    episode_repo: EpisodeRepository

    async def execute(self, *, script_id: ScriptId, requester_id: UserId) -> None:
        script = await self.script_repo.get(script_id)
        if script is None:
            raise ScriptNotFound(f"script {script_id} not found")
        pod = await self.pod_repo.get(script.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("script belongs to a pod owned by a different user")

        episodes = await self.episode_repo.list_for_pod(script.pod_id)
        if any(ep.script_id == script_id for ep in episodes):
            raise ConflictError(
                f"cannot delete script {script_id}: one or more episodes "
                "still reference it"
            )

        await self.script_repo.delete(script_id)


_REVIEW_SYSTEM = (
    "You are 'The Supervisor', a veteran Animation Director. Your job is to "
    "strictly enforce video creation rules, ensuring clean transitions, logical "
    "pacing, and adherence to continuity guidelines without breaking the JSON "
    "structure."
)


def _render_review_prompt(*, draft_json: str, language: str) -> str:
    return (
        f"Here is a drafted episode script.\n\n"
        f"## DRAFT SCRIPT (JSON)\n{draft_json}\n\n"
        f"## YOUR MISSION\n"
        f"1. Enforce the video rules below perfectly.\n"
        f"2. Fix transitions: Use 'cut' strictly for action changes. "
        f"Use 'continue' only for static moments.\n"
        f"3. Make sure `audio_text` is pure spoken dialogue in {language}.\n"
        f"4. Make sure `visual_prompt` is pure physical description in ENGLISH "
        f"with NO DIALOGUE text inside.\n"
        f"5. Improve pacing (`duration_seconds`).\n"
        f"6. Improve camera usage — vary shot_type, movement, and angle "
        f"narratively; match them to mood and narrative_phase.\n\n"
        f"{_VIDEO_RULES}\n\n"
        f"## OUTPUT FORMAT\n"
        f"Return ONLY the corrected JSON matching the supplied schema."
    )


def _scenes_to_draft(scenes: list[Scene]) -> list[dict[str, Any]]:
    """Serialize scenes into the LLM-facing draft format, using raw data when available."""
    out: list[dict[str, Any]] = []
    for sc in scenes:
        if sc.raw:
            out.append(sc.raw)
        else:
            entry: dict[str, Any] = {
                "scene_number": sc.index + 1,
                "visual_prompt": sc.visual_prompt,
                "audio_text": sc.audio_text or "",
                "transition_to_next": sc.transition,
                "duration_seconds": sc.duration_s,
            }
            if sc.camera_shot:
                entry["camera"] = {
                    "shot_type": sc.camera_shot,
                    "movement": sc.camera_movement or "static",
                    "angle": sc.camera_angle or "eye_level",
                }
            out.append(entry)
    return out


@dataclass(frozen=True, slots=True)
class ReviewScript:
    """Second LLM pass — validates and corrects a generated script.

    Acts as the legacy ReviewerEngine (layer 3 of the 5-layer camera system):
    enforces transition semantics, fixes dialogue leaks in visual_prompt,
    improves camera direction, and corrects pacing.
    """

    pod_repo: PodRepository
    script_repo: ScriptRepository
    llm: LLMPort

    async def execute(
        self, *, pod_id: PodId, script_id: ScriptId, requester_id: UserId,
    ) -> Script:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")

        script = await self.script_repo.get(script_id)
        if script is None or script.pod_id != pod_id:
            raise ScriptNotFound(f"script {script_id} not found in pod {pod_id}")

        draft = _scenes_to_draft(script.scenes)
        draft_json = json.dumps({"title": script.title, "scenes": draft}, indent=2)

        prompt = (
            f"{_REVIEW_SYSTEM}\n\n"
            + _render_review_prompt(
                draft_json=draft_json,
                language=pod.config.language,
            )
        )
        # Enforce the same minimum scene floor as GenerateScript — the reviewer
        # must not shrink the script below the duration target.
        min_scenes, _ = _scene_count_targets(
            pod.config.duration_seconds, pod.config.max_clip_seconds
        )
        review_schema = copy.deepcopy(_SCENE_SCHEMA)
        review_schema["properties"]["scenes"]["minItems"] = min_scenes
        raw = await self.llm.complete(
            prompt, response_schema=review_schema, temperature=0.4,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        reviewed_scenes = [
            _to_scene(i, s)
            for i, s in enumerate(data.get("scenes") or [])
            if isinstance(s, dict) and "visual_prompt" in s
        ]
        updated = script.model_copy(update={
            "scenes": reviewed_scenes,
            "title": str(data.get("title") or script.title),
            "summary": data.get("summary") or script.summary,
            "reviewed": True,
            "version": script.version + 1,
        })
        return await self.script_repo.save(updated)


__all__ = ["DeleteScript", "GenerateScript", "ListScripts", "ReviewScript"]
