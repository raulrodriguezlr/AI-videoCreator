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
import math
import re
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Character, Scene, Script
from videocreator.domain.value_objects import NarrationStyle, SettingMode
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
    ValidationError,
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
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Spoken-pace contract — words ↔ seconds
# ---------------------------------------------------------------------------
#: Spoken pace assumed across the whole pipeline. The prose word budget, the
#: per-scene speech budget and the deterministic pacing guard all derive from
#: this single figure (~Spanish TTS at the default 1.15x rate), so the story is
#: written, split and timed against the same words↔seconds relationship.
SPOKEN_WORDS_PER_SECOND = 2.2

#: Floor for a split chunk's duration (matches the engine's MIN_SCENE_DURATION).
_MIN_CHUNK_SECONDS = 4
_MIN_CHUNK_WORDS = 5

_SENTENCE_RE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")


def _word_count(text: str | None) -> int:
    return len((text or "").split())


def _story_word_target(target_duration_s: int) -> int:
    """Total spoken words the storyteller should write for the episode."""
    return max(180, int(target_duration_s * SPOKEN_WORDS_PER_SECOND))


def _scene_word_budget(duration_s: float) -> int:
    """Max spoken words that fit ``duration_s`` at the contract pace."""
    return max(1, int(duration_s * SPOKEN_WORDS_PER_SECOND))


def _split_sentences(text: str) -> list[str]:
    """Split into sentences keeping their punctuation; never returns empties."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [m.group().strip() for m in _SENTENCE_RE.finditer(text)]
    return [p for p in parts if p] or [text]


def _pack_sentences(text: str, max_words: int) -> list[str]:
    """Greedily group sentences into chunks of at most ``max_words`` words.

    A single sentence longer than ``max_words`` is hard-split by word count so a
    chunk never overflows the budget.
    """
    chunks: list[str] = []
    cur: list[str] = []
    cur_n = 0
    for sent in _split_sentences(text):
        n = _word_count(sent)
        if n > max_words:
            if cur:
                chunks.append(" ".join(cur))
                cur, cur_n = [], 0
            words = sent.split()
            for k in range(0, len(words), max_words):
                chunks.append(" ".join(words[k:k + max_words]))
            continue
        if cur and cur_n + n > max_words:
            chunks.append(" ".join(cur))
            cur, cur_n = [sent], n
        else:
            cur.append(sent)
            cur_n += n
    if cur:
        chunks.append(" ".join(cur))
    return chunks or [text.strip()]


def _trim_to_word_ceiling(prose: str, max_words: int) -> str:
    """Truncate *prose* to the last complete sentence within *max_words*."""
    if _word_count(prose) <= max_words:
        return prose
    sentences = _split_sentences(prose)
    kept: list[str] = []
    total = 0
    for sent in sentences:
        n = _word_count(sent)
        if total + n > max_words and kept:
            break
        kept.append(sent)
        total += n
    return " ".join(kept)


def _dedup_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop consecutive scenes whose spoken line repeats the previous one.

    The LLM sometimes pads to the requested scene count with duplicate
    greeting/farewell beats (the "scenes 11-13 identical" bug). Collapse runs of
    identical normalized ``audio_text``, keeping the first.
    """
    out: list[dict[str, Any]] = []
    prev: str | None = None
    for s in scenes:
        norm = " ".join((s.get("audio_text") or "").lower().split())
        if norm and norm == prev:
            continue
        out.append(s)
        prev = norm
    return out


def _scene_duration(s: dict[str, Any], default: float) -> float:
    return float(s.get("duration_seconds") or s.get("duration_s") or default)


def _enforce_pacing(
    scenes: list[dict[str, Any]], max_clip_seconds: int
) -> list[dict[str, Any]]:
    """Make every scene's ``audio_text`` fit its duration at the contract pace.

    For an overflowing scene: first raise its duration toward
    ``max_clip_seconds``; if the line still doesn't fit, split it across
    consecutive ``continue`` scenes (same ``visual_prompt`` — the engine's
    ``continue`` rule seamlessly extends the clip), each sized to its own word
    count. The last chunk keeps the original transition.
    """
    ceiling = max(1, int(max_clip_seconds))
    max_budget = _scene_word_budget(ceiling)
    out: list[dict[str, Any]] = []
    for s in scenes:
        text = s.get("audio_text") or ""
        words = _word_count(text)
        duration = _scene_duration(s, ceiling)
        if words <= _scene_word_budget(duration):
            out.append(s)
            continue
        if words <= max_budget:
            bumped = max(duration, math.ceil(words / SPOKEN_WORDS_PER_SECOND))
            out.append({**s, "duration_seconds": min(ceiling, bumped)})
            continue
        chunks = _pack_sentences(text, max_budget)
        if len(chunks) > 1 and _word_count(chunks[-1]) <= _MIN_CHUNK_WORDS:
            chunks[-2] = chunks[-2] + " " + chunks[-1]
            chunks.pop()
        if len(chunks) > 1 and _word_count(chunks[0]) <= _MIN_CHUNK_WORDS:
            chunks[1] = chunks[0] + " " + chunks[1]
            chunks.pop(0)
        orig_transition = s.get("transition_to_next") or s.get("transition") or "cut"
        last = len(chunks) - 1
        for j, chunk in enumerate(chunks):
            part = {**s}
            part["audio_text"] = chunk
            part["duration_seconds"] = min(
                ceiling,
                max(_MIN_CHUNK_SECONDS, math.ceil(_word_count(chunk) / SPOKEN_WORDS_PER_SECOND)),
            )
            part["transition_to_next"] = orig_transition if j == last else "continue"
            if "transition" in part:
                part["transition"] = part["transition_to_next"]
            out.append(part)
    return out


def _enforce_duration_floor(
    scenes: list[dict[str, Any]], target_s: int, max_clip_seconds: int
) -> list[dict[str, Any]]:
    """Top up scene durations so they sum to at least ``target_s``.

    Word count is the real driver of length (guaranteed upstream by the
    storyteller word floor); this only absorbs rounding. Durations are raised
    toward ``max_clip_seconds`` — never by fabricating filler scenes. If even all
    scenes at the ceiling can't reach the target, the content is genuinely short:
    log it rather than pad with silence.
    """
    if not scenes:
        return scenes
    ceiling = max(1, int(max_clip_seconds))
    total = sum(_scene_duration(s, ceiling) for s in scenes)
    if total >= target_s:
        return scenes
    if ceiling * len(scenes) < target_s:
        log.warning(
            "script.duration_floor_unreachable",
            target_s=target_s, scenes=len(scenes), max_total=ceiling * len(scenes),
        )
    deficit = target_s - total
    out = [dict(s) for s in scenes]
    for s in out:
        if deficit <= 0:
            break
        d = _scene_duration(s, ceiling)
        room = ceiling - d
        if room <= 0:
            continue
        add = min(room, deficit)
        s["duration_seconds"] = d + add
        deficit -= add
    return out


def _enforce_duration_ceiling(
    scenes: list[dict[str, Any]], target_s: int, max_clip_seconds: int
) -> list[dict[str, Any]]:
    """Trim total duration down to ``target_s * 1.15`` when the LLM overshoots.

    Phase 1: shrink scene durations toward their speech-minimum (words/WPS).
    Phase 2: drop trailing scenes if still over budget.
    """
    if not scenes:
        return scenes
    ceiling_s = int(target_s * 1.15)
    clip_ceil = max(1, int(max_clip_seconds))
    total = sum(_scene_duration(s, clip_ceil) for s in scenes)
    if total <= ceiling_s:
        return scenes
    out = [dict(s) for s in scenes]
    # Phase 1: shrink from tail
    for s in reversed(out):
        if total <= ceiling_s:
            break
        d = _scene_duration(s, clip_ceil)
        words = _word_count(s.get("audio_text") or "")
        min_d = max(_MIN_CHUNK_SECONDS, math.ceil(words / SPOKEN_WORDS_PER_SECOND))
        shrink = d - min_d
        if shrink <= 0:
            continue
        trim = min(shrink, total - ceiling_s)
        s["duration_seconds"] = d - trim
        total -= trim
    # Phase 2: drop trailing scenes
    min_scenes = max(1, -(-target_s // clip_ceil))
    while total > ceiling_s and len(out) > min_scenes:
        removed = out.pop()
        total -= _scene_duration(removed, clip_ceil)
    if total > ceiling_s:
        log.warning(
            "script.duration_ceiling_unreachable",
            target_s=target_s, ceiling_s=ceiling_s, actual_s=total,
        )
    return out


def _render_story_extension_prompt(
    story_so_far: str, extra_words: int, language: str
) -> str:
    """Continuation prompt when the first storyteller pass came back too short."""
    return (
        "The story below is too SHORT to fill the episode.\n"
        f"Continue the SAME story in {language}, adding about {extra_words} more "
        "words of real spoken dialogue/narration. Deepen Act 2 (exploration, "
        "obstacle, discovery) — do NOT restart, do NOT repeat the greeting or "
        "farewell, do NOT summarise. Pick up naturally where it stops and write "
        "ONLY the continuation.\n\n"
        f"## STORY SO FAR\n{story_so_far.strip()}\n"
    )


# ---------------------------------------------------------------------------
# Video rules — camera vocabulary + transition semantics + guard rails
# (Legacy: PromptManager.load_video_rules() read pods/video_rules.json)
# ---------------------------------------------------------------------------
_VIDEO_RULES = """\
## VIDEO PRODUCTION RULES (MANDATORY)

### TRANSITIONS (transition_to_next)
- **continue** — Fluid static continuation. Use this MANDATORILY when splitting \
a long dialogue across multiple scenes to fit the duration. The visual_prompt \
MUST be exactly the same as the previous scene so the generator seamlessly \
extends the clip. If there is physical movement, pose change, or new objects, \
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
- visual_prompt MUST NOT contain dialogue or quotes. Do not write 'X says ...' or ANY 'X says "..."' pattern inside visual_prompt.
- visual_prompt contains ONLY physical descriptions: actions, environment, expressions, poses. ZERO dialogue text.
- All spoken dialogue goes EXCLUSIVELY in the audio_text field. YOU MUST WRITE DIALOGUE (audio_text) for the characters to speak! Do NOT leave it empty.
- When a character speaks, prefer 'close-up' or 'medium' shots.

### VISUAL CONTINUITY
- ALWAYS describe the full physical appearance of ALL characters and entities in EVERY \
visual_prompt (clothing, colors, species, accessories). If there is a secondary character or creature (like an animal, monster, or friends), describe them explicitly in EVERY scene they appear so they don't change appearance or turn into humans. For established characters, you MUST strictly follow their provided [look: ...] description. If their look description does not mention specific clothing, DO NOT invent clothing for them.
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
- 6-7 seconds: Short dialogue (1-2 sentences), simple action, exploration.
- 8 seconds: Establishing scenes, emotional climax, important moments.
- IF a character speaks a lot of text, DO NOT cram it into one scene. \
Instead, SPLIT the dialogue across 2 or 3 consecutive scenes and use the \
'continue' transition between them to create one long synthetic clip.
"""

# ---------------------------------------------------------------------------
# Dialogue & story quality — the rules that stop the LLM writing "¡Gol!"/"¡Sí!"
# placeholder dialogue and wasting scenes on greetings/farewells. Injected into
# BOTH the storyteller (creative) and director (formatting) passes.
# ---------------------------------------------------------------------------
_DIALOGUE_QUALITY = """\
## DIALOGUE & STORY QUALITY (CRITICAL — THIS IS THE PRIORITY)
The spoken dialogue is the heart of the episode. Weak dialogue ruins it.
- FORBIDDEN: empty filler or one-word exclamations as a whole line — e.g. \
'¡Sí!', '¡Pum!', '¡Gol!', '¡Vamos!', '¡Ay!', '¡Guau!', '¡Lo logré!'. Every line \
must carry meaning, teach something, or move the story.
- Characters must actually CONVERSE and develop: ask real questions, explain \
ideas in their own voice, react with specific feelings, reference what just \
happened. Show curiosity and personality.
- NARRATIVE WEIGHT (mandatory): ~10% hook/intro, ~70% development + conflict \
(the real substance — explore the topic deeply, the characters struggle, \
discover, learn), ~20% climax + resolution.
- GREETINGS/FAREWELLS: a warm, direct-to-audience greeting at the very start is \
GOOD and on-brand (e.g. "¡Hola, soy Tico! Bienvenidos al bosque mágico") — keep \
it. Just don't REPEAT it: at most ONE greeting beat and ONE farewell beat, never \
several scenes of 'hola' or 'adiós/hasta la próxima'.
- There MUST be a real obstacle, mystery, or question driving the middle — not a \
flat list of facts or actions.
- Age-appropriate but never dumbed-down: warm, witty, curious, specific.
"""

# ---------------------------------------------------------------------------
# Storyteller pass — pure creative writing, NO json/camera/durations. Produces a
# rich narrative with real dialogue that the director pass then formats.
# ---------------------------------------------------------------------------
_STORYTELLER_SYSTEM = (
    "You are a master storyteller and screenwriter for children's animated "
    "series, in the tradition of Pixar and Studio Ghibli. You write warm, witty, "
    "emotionally rich stories with memorable dialogue and real dramatic stakes."
)


def _render_storyteller_prompt(
    *, series_name: str, language: str, target_duration_s: int,
    topic_title: str, topic_description: str | None,
    series_context: str | None, characters: list[Character],
    episode_memory: str | None = None,
    interactive_questions: int = 0,
    narration_style: object = NarrationStyle.FOURTH_WALL,
    setting_mode: object = SettingMode.IN_SCENE,
    prompt_story_suffix: str = "",
) -> str:
    """Prompt for the creative pass — prose story only, no technical formatting."""
    ctx = series_context.strip() if series_context else "(no extra context)"
    desc = topic_description.strip() if topic_description else "(no description)"
    char_block = _format_characters(characters)
    memory = (episode_memory or "").strip()
    memory_block = (
        f"\n## PREVIOUS EPISODES (for continuity — reference when natural)\n{memory}\n"
        if memory else ""
    )
    word_target = _story_word_target(target_duration_s)
    result = (
        f"{_STORYTELLER_SYSTEM}\n\n"
        f"Write the script for one episode of '{series_name}', a children's "
        f"series. Write it as a STORY (prose + dialogue) in {language} — NOT as "
        f"JSON, with NO camera directions, NO scene numbers, and NO durations. "
        f"Pure storytelling.\n\n"
        f"## SERIES CONTEXT\n{ctx}\n"
        f"{memory_block}\n"
        f"## CHARACTERS\n{char_block}\n\n"
        f"## TOPIC OF THIS EPISODE\n{topic_title}\n{desc}\n\n"
        f"## STRUCTURE (3 acts)\n"
        f"- Act 1 (~10%): a short, fresh hook that drops us into the topic. ONE "
        f"greeting at most (if the main character usually introduces themselves, e.g. 'Hola amigos, soy...', keep that personality!).\n"
        f"- Act 2 (~70%): the heart. The characters explore the topic in DEPTH "
        f"through real dialogue and a genuine obstacle/mystery/challenge. They "
        f"ask questions, reason, struggle, and learn. This is where the value is.\n"
        f"- Act 3 (~20%): a satisfying climax and resolution. ONE farewell at most.\n\n"
        f"{_show_format_block(narration_style, setting_mode)}"
        f"{_interactive_block(interactive_questions)}\n"
        f"{_DIALOGUE_QUALITY}\n\n"
        f"## LENGTH\n"
        f"You MUST write between {word_target} and {int(word_target * 1.15)} words "
        f"of spoken dialogue/narration so it fills about {target_duration_s} seconds "
        f"of video — no shorter AND no longer. Favour substance in Act 2 over a "
        f"long intro or outro.\n"
        f"Write the dialogue in SHORT spoken beats: each character line is ONE "
        f"breath (≤ ~17 words), not a paragraph, so it maps cleanly to one short "
        f"scene. Resolve every question you pose to the viewer before the "
        f"farewell — never leave an open question dangling.\n\n"
        f"Write the full story now, with the characters' lines clearly attributed."
    )
    if (prompt_story_suffix or "").strip():
        result += f"\n\n## ADDITIONAL INSTRUCTIONS\n{prompt_story_suffix.strip()}\n"
    return result


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
                    "visual_prompt": {"type": "string", "minLength": 1},
                    # minLength forces the structured-output grammar to emit
                    # real dialogue — local models (qwen2.5) otherwise return an
                    # empty string here, leaving scenes silent.
                    "audio_text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The exact spoken dialogue/narration for "
                        "this scene, in the target language. Never empty.",
                    },
                    "character": {
                        "type": "string",
                        "description": "The exact name of the character speaking this line. If it is general narration not tied to a specific character, use 'Narrador'.",
                    },
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
                    "visual_prompt", "audio_text", "character", "camera",
                    "mood", "lighting", "transition_to_next",
                    "duration_seconds",
                ],
            },
        },
    },
    "required": ["title", "scenes"],
}


#: Free-text role values that map to each narrative role group.
_PROTAGONIST_ROLES = {"protagonist", "protagonista", "principal", "lead", "main", "hero"}
_ANTAGONIST_ROLES = {"antagonist", "antagonista", "villain", "villano"}


def _role_group(role: str | None) -> str:
    r = (role or "").strip().lower()
    if r in _PROTAGONIST_ROLES:
        return "protagonist"
    if r in _ANTAGONIST_ROLES:
        return "antagonist"
    return "secondary"


def _format_characters(characters: list[Character]) -> str:
    """Format the registered cast for the LLM, grouped by role.

    Hard rule: the writer uses ONLY these characters. The protagonist anchors
    every episode; secondary/antagonist characters appear ONLY when they serve
    the story — the LLM decides which (if any), they do NOT all show up at once.
    This stops the generator inventing un-registered recurring characters (kids,
    a dragon, "friends") that have no reference image and break visual continuity.
    """
    if not characters:
        return ("(no characters registered — tell the story with a single warm "
                "narrator/host; do NOT invent named characters)")

    groups: dict[str, list[Character]] = {"protagonist": [], "secondary": [], "antagonist": []}
    for c in characters:
        groups[_role_group(c.role)].append(c)
    if not groups["protagonist"]:
        # No explicit lead set — promote the first character so the story still
        # has an anchor (e.g. legacy characters all default to "supporting").
        first = characters[0]
        groups[_role_group(first.role)].remove(first)
        groups["protagonist"].append(first)

    def _line(c: Character) -> str:
        parts = [f"- **{c.name}**"]
        if c.personality:
            parts.append(f"— {c.personality}")
        if c.look_description:
            parts.append(f"[look: {c.look_description}]")
        return " ".join(parts)

    out: list[str] = [
        "## CAST — use ONLY these characters (NEVER invent new named ones)",
        "RULES:",
        "- Use the EXACT names below. Never add surnames or real-world identities "
        "(if a name is 'Cristiano', never write 'Cristiano Ronaldo').",
        "- The PROTAGONIST(S) drive every episode and are ALWAYS present.",
        "- SECONDARY / ANTAGONIST characters appear ONLY when they genuinely serve "
        "THIS episode. YOU decide which (if any) show up — do NOT force them all in; "
        "an episode may star the protagonist alone.",
        "- You MUST NOT introduce new recurring named characters not listed here. An "
        "incidental, silent background creature (a passing blue bird, a fish) is fine, "
        "but never a named character with dialogue or a recurring presence.",
    ]
    if groups["protagonist"]:
        out.append("\nPROTAGONIST(S) — always present:")
        out += [_line(c) for c in groups["protagonist"]]
    if groups["secondary"]:
        out.append("\nSECONDARY — optional, include only if they fit this episode:")
        out += [_line(c) for c in groups["secondary"]]
    if groups["antagonist"]:
        out.append("\nANTAGONIST(S) — optional, only if this episode needs their conflict:")
        out += [_line(c) for c in groups["antagonist"]]
    return "\n".join(out)


#: StyleProfile (the pod-settings dropdown) → a visual-style description for the
#: script's visual_prompts. Without this, changing the dropdown did nothing —
#: the script only read the free-text `art_style`, so it kept the old look.
_STYLE_DESCRIPTIONS = {
    "cinematic_3d": "cinematic 3D animation, Pixar/Disney quality",
    "anime_2d": "2D anime style",
    "stock_montage": "realistic live-action stock-footage montage",
    "talking_head_avatar": "talking-head avatar presenter style",
    "photoreal_doc": "photorealistic documentary style",
    "kids_3d": "kid-friendly colorful 3D animation",
}


def _style_label(style_profile: object, art_style: str | None) -> str:
    """Effective visual style: the pod's `style_profile` (so changing the dropdown
    actually changes the visuals) plus any free-text `art_style` detail."""
    key = getattr(style_profile, "value", style_profile) or "cinematic_3d"
    base = _STYLE_DESCRIPTIONS.get(str(key), "3D animation")
    extra = (art_style or "").strip()
    if extra and extra.lower() not in base.lower():
        return f"{base} — {extra}"
    return base


def _clean_json(raw: str) -> str:
    """Strip markdown backticks that local LLMs sometimes hallucinate."""
    s = raw.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


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


_NARRATION_BLOCKS: dict[NarrationStyle, str] = {
    NarrationStyle.FOURTH_WALL: (
        "NARRATIVE VOICE — FOURTH WALL (host speaks to the viewer):\n"
        "- The protagonist/host talks DIRECTLY to the audience, Dora-the-Explorer "
        "style. ONE warm welcome at the very start (e.g. '¡Hola amigos! Soy "
        "[Name]...') and ONE goodbye at the end.\n"
        "- The host TAKES THE AUDIENCE on the journey in first person — narrate the "
        "topic to the viewer.\n"
        "- Do NOT invent other characters (kids, students, sidekicks) whose only "
        "job is to ask the host questions as a framing device. The host addresses "
        "the viewer directly, not a group of on-screen listeners."
    ),
    NarrationStyle.IMMERSIVE: (
        "NARRATIVE VOICE — IMMERSIVE (characters act among themselves):\n"
        "- Characters live the story and converse with EACH OTHER. They do NOT look "
        "at or address the camera/viewer. No 'hello audience', no direct questions "
        "to the viewer.\n"
        "- The viewer is an unseen observer of a self-contained world."
    ),
    NarrationStyle.VOICEOVER: (
        "NARRATIVE VOICE — VOICEOVER (off-screen narrator):\n"
        "- An off-screen narrator tells the story over the action. On-screen "
        "characters act within the scene; the narrator guides the viewer and may "
        "address them warmly, but the characters themselves do not break the 4th wall."
    ),
}

_SETTING_BLOCKS: dict[SettingMode, str] = {
    SettingMode.IN_SCENE: (
        "SETTING — IN THE ACTION:\n"
        "- Narrate FROM the real setting of the topic. If the episode is about space, "
        "the host/characters are IN SPACE among the planets and stars — NEVER on "
        "Earth in front of a blackboard or in a classroom merely talking about it.\n"
        "- The narration happens inside the actual scenes, surrounded by the subject."
    ),
    SettingMode.FRAMING_DEVICE: (
        "SETTING — HOST FRAME:\n"
        "- A consistent host location frames the episode (e.g. a cozy studio or "
        "classroom). Cut between that frame and vivid scenes of the topic itself."
    ),
}


def _show_format_block(narration_style: object, setting_mode: object) -> str:
    """Per-pod SHOW FORMAT rules (narrative voice + setting), chosen in the wizard.

    Replaces the 4th-wall instruction that used to be hardcoded for every pod.
    Accepts the enums or their string values; unknown values fall back to the
    legacy defaults (4th-wall, in-scene)."""
    def _coerce(enum_cls, val, default):  # type: ignore[no-untyped-def]
        if isinstance(val, enum_cls):
            return val
        try:
            return enum_cls(str(getattr(val, "value", val)))
        except ValueError:
            return default

    ns = _coerce(NarrationStyle, narration_style, NarrationStyle.FOURTH_WALL)
    sm = _coerce(SettingMode, setting_mode, SettingMode.IN_SCENE)
    return (
        "## SHOW FORMAT (apply consistently in EVERY episode)\n"
        f"{_NARRATION_BLOCKS[ns]}\n\n"
        f"{_SETTING_BLOCKS[sm]}\n"
    )


def _render_script_prompt(
    *, series_name: str, language: str, target_duration_s: int,
    topic_title: str, topic_description: str | None,
    series_context: str | None, art_style: str | None,
    characters: list[Character],
    episode_memory: str | None = None,
    max_clip_seconds: int = 8,
    interactive_questions: int = 0,
    story_narrative: str | None = None,
    narration_style: object = NarrationStyle.FOURTH_WALL,
    setting_mode: object = SettingMode.IN_SCENE,
    prompt_suffix: str = "",
) -> str:
    """Build the full script-generation prompt with video rules and camera vocabulary.

    This restores the legacy 5-layer camera pipeline: the video rules inject the
    closed camera vocabulary, the schema enforces it, and the prompt tells the LLM
    to use it narratively.

    When ``story_narrative`` is supplied (the storyteller pass ran first), the
    prompt switches from *inventing* a story to *adapting* the given one into
    scenes — preserving its rich dialogue instead of regenerating shallow lines.
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

    if story_narrative and story_narrative.strip():
        role = (
            f"You are the technical director for '{series_name}'. You are handed a "
            f"FINISHED story and must storyboard it into a strict JSON cinematic "
            f"script ready for Generative AI video models."
        )
        story_block = (
            "\n## SOURCE STORY — ADAPT THIS, DO NOT INVENT A NEW ONE\n"
            f"{story_narrative.strip()}\n"
            "Convert the story above into the scene JSON. PRESERVE its dialogue as "
            "`audio_text` (you may split one long line across consecutive scenes, "
            "but NEVER replace it with empty exclamations or simplify it). Keep its "
            "narrative weight: do not collapse the middle (Act 2) and do not expand "
            "the greeting or farewell.\n"
            "CRITICAL FOR VISUALS: Since you don't have to invent the story, focus your effort on making the `visual_prompt` extremely detailed. Explicitly describe the physical appearance of ALL entities (including new creatures, animals, or friends) in EVERY scene they appear to ensure visual consistency.\n"
        )
    else:
        role = (
            f"You are the head director and screenwriter for '{series_name}', "
            f"with Pixar/Disney cinematic experience. Generate a strict JSON "
            f"cinematic script ready for Generative AI video models."
        )
        story_block = ""

    result = (
        f"{role}\n"
        f"Provide physical visual prompts in ENGLISH and audio dialogues in "
        f"{language}.\n\n"
        f"## SERIES CONTEXT\n{ctx}\n"
        f"{memory_block}\n"
        f"## CHARACTERS\n{char_block}\n"
        f"{_show_format_block(narration_style, setting_mode)}"
        f"{story_block}\n"
        f"## TOPIC\n{topic_title}\n{desc}\n\n"
        f"{_DIALOGUE_QUALITY}\n"
        f"## ART STYLE\n{style}\n"
        f"Every visual_prompt MUST start with this art style prefix.\n\n"
        f"## DURATION (STRICT — NON-NEGOTIABLE)\n"
        f"- The episode MUST total between {target_duration_s} and {int(target_duration_s * 1.15)} seconds of video.\n"
        f"- You MUST generate around {typical_scenes} scenes. Do not generate significantly fewer or many more.\n"
        f"- Each scene should be between 4 and {max_clip_seconds} seconds long.\n"
        f"- VARY the `duration_seconds` narratively! Do NOT make every scene the exact same length (e.g. don't make them all 5). Use shorter times (4 or 5) for quick dialogue/action and longer times (7 or 8) for establishing/complex shots. The value MUST be a single number.\n"
        f"- The SUM of every scene's `duration_seconds` MUST be >= {target_duration_s} AND <= {int(target_duration_s * 1.15)}.\n"
        f"- No single scene may exceed {max_clip_seconds} seconds.\n"
        f"- A script below {target_duration_s}s or above {int(target_duration_s * 1.15)}s is INVALID. Tell the story across EXACTLY {typical_scenes} short, dynamic scenes.\n"
        f"- Each scene needs a vivid visual_prompt and audio_text.\n"
        f"## PER-SCENE SPEECH BUDGET (STRICT)\n"
        f"- audio_text MUST be speakable within its duration_seconds at ~{SPOKEN_WORDS_PER_SECOND:g} words/sec: "
        f"max words ≈ {SPOKEN_WORDS_PER_SECOND:g} × duration_seconds (5s≈11, 6s≈13, 8s≈17 words).\n"
        f"- If a line is longer, SPLIT it across consecutive scenes with transition_to_next='continue' and the SAME visual_prompt — never cram a paragraph into one short clip.\n"
        f"- NEVER repeat the same audio_text in two scenes. Do NOT pad with duplicate greeting/farewell scenes to reach the scene count; if you need more scenes, split real dialogue.\n\n"
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
        f"- `moral`: one sentence stating the concrete lesson of THIS episode's actual events (from the SOURCE STORY). Never a generic line unrelated to what happened.\n"
        f"- `ambient_audio_prompt`: short English music prompt describing the "
        f"episode's overall ambient mood (e.g. 'soft orchestral adventure music "
        f"with gentle woodwinds, warm and uplifting').\n\n"
        f"Return strict JSON matching the supplied schema."
    )
    if (prompt_suffix or "").strip():
        result += f"\n\n## ADDITIONAL INSTRUCTIONS\n{prompt_suffix.strip()}\n"
    return result


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
class WriteStory:
    """Creative pass — write a rich prose story with real dialogue.

    This is step 1 of the two-pass pipeline. It frees the LLM from JSON/camera/
    duration constraints so it focuses purely on a good story and deep dialogue;
    `GenerateScript` then storyboards the result into scenes. Returns plain text.
    """

    pod_repo: PodRepository
    topic_repo: TopicRepository
    character_repo: CharacterRepository
    llm: LLMPort

    async def execute(
        self, *, pod_id: PodId, topic_id: TopicId, requester_id: UserId,
    ) -> str:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        topic = await self.topic_repo.get(topic_id)
        if topic is None or topic.pod_id != pod_id:
            raise PodNotFound(f"topic {topic_id} not found in pod {pod_id}")

        characters = await self.character_repo.list_for_pod(pod_id)
        prompt = _render_storyteller_prompt(
            series_name=pod.config.series_name,
            language=pod.config.language,
            target_duration_s=pod.config.duration_seconds,
            topic_title=topic.title,
            topic_description=topic.description,
            series_context=pod.config.series_context,
            characters=characters,
            episode_memory=pod.config.universe_memory,
            interactive_questions=pod.config.interactive_questions,
            narration_style=pod.config.narration_style,
            setting_mode=pod.config.setting_mode,
            prompt_story_suffix=pod.config.extra.get("script_overrides", {}).get("prompt_story_suffix", ""),
        )
        # No response_schema: we want free prose, not JSON. Higher temperature
        # for creativity. Returned verbatim and fed into GenerateScript.
        prose = await self.llm.complete(prompt, temperature=0.9)

        # Duration floor: total episode length tracks the spoken word count. If
        # the model stopped short, ask it once to EXTEND (not restart) so the
        # scenes can actually sum to the requested duration instead of falling
        # short — the root cause of "asked 120s, got 80s".
        word_target = _story_word_target(pod.config.duration_seconds)
        if _word_count(prose) < int(word_target * 0.9):
            deficit = word_target - _word_count(prose)
            extra = await self.llm.complete(
                _render_story_extension_prompt(prose, deficit, pod.config.language),
                temperature=0.9,
            )
            if extra.strip():
                prose = f"{prose.rstrip()}\n\n{extra.lstrip()}"
        word_ceiling = int(word_target * 1.15)
        if _word_count(prose) > word_ceiling:
            prose = _trim_to_word_ceiling(prose, word_ceiling)
        return prose


@dataclass(frozen=True, slots=True)
class GenerateScript:
    pod_repo: PodRepository
    topic_repo: TopicRepository
    script_repo: ScriptRepository
    character_repo: CharacterRepository
    llm: LLMPort

    async def execute(
        self, *, pod_id: PodId, topic_id: TopicId, requester_id: UserId,
        story_narrative: str | None = None,
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
            art_style=_style_label(pod.config.style_profile, pod.config.art_style),
            characters=characters,
            episode_memory=pod.config.universe_memory,
            max_clip_seconds=pod.config.max_clip_seconds,
            interactive_questions=pod.config.interactive_questions,
            story_narrative=story_narrative,
            narration_style=pod.config.narration_style,
            setting_mode=pod.config.setting_mode,
            prompt_suffix=pod.config.extra.get("script_overrides", {}).get("prompt_suffix", ""),
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
            data = json.loads(_clean_json(raw))
        except json.JSONDecodeError as exc:
            # Add a bit of the raw output to the error message for easier debugging
            raise ProviderError(f"LLM returned invalid JSON. Snippet: {raw[:100]}... Error: {exc}") from exc

        # Deterministic guard: the LLM doesn't reliably honour the per-scene
        # speech budget or the no-duplicates rule, so repair the raw scenes here.
        # dedup → kill padded clone scenes; pacing → fit/split overflowing lines;
        # floor → top up durations toward the requested episode length.
        raw_scenes = [s for s in (data.get("scenes") or [])
                      if isinstance(s, dict) and "visual_prompt" in s]
        raw_scenes = _dedup_scenes(raw_scenes)
        raw_scenes = _enforce_pacing(raw_scenes, pod.config.max_clip_seconds)
        raw_scenes = _enforce_duration_floor(
            raw_scenes, pod.config.duration_seconds, pod.config.max_clip_seconds,
        )
        raw_scenes = _enforce_duration_ceiling(
            raw_scenes, pod.config.duration_seconds, pod.config.max_clip_seconds,
        )
        scenes = [_to_scene(i, s) for i, s in enumerate(raw_scenes)]
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
        # Also drop this script's line from the pod's universe_memory (added by
        # GenerateScript as `- "<title>": ...`) so deleted content stops leaking
        # into future scripts' continuity context.
        await _strip_universe_memory(self.pod_repo, pod, script.title)


async def _strip_universe_memory(pod_repo, pod, title: str | None) -> None:
    """Remove the `- "<title>": …` entry (added per generated script) from the
    pod's universe_memory. No-op when nothing matches."""
    mem = pod.config.universe_memory or ""
    if not (mem and title):
        return
    kept = [l for l in mem.splitlines() if not l.lstrip().startswith(f'- "{title}"')]
    new_mem = "\n".join(kept)
    if new_mem != mem:
        await pod_repo.save(pod.model_copy(
            update={"config": pod.config.model_copy(update={"universe_memory": new_mem})}
        ))


_REVIEW_SYSTEM = (
    "You are 'The Supervisor', a veteran Animation Director. Your job is to "
    "strictly enforce video creation rules, ensuring clean transitions, logical "
    "pacing, and adherence to continuity guidelines without breaking the JSON "
    "structure."
)


def _render_review_prompt(*, draft_json: str, language: str, typical_scenes: int) -> str:
    return (
        f"Here is a drafted episode script.\n\n"
        f"## DRAFT SCRIPT (JSON)\n{draft_json}\n\n"
        f"## YOUR MISSION\n"
        f"1. Enforce the video rules below perfectly.\n"
        f"2. Fix transitions: Use 'cut' strictly for action changes. "
        f"Use 'continue' only for static moments.\n"
        f"3. Make sure `audio_text` is pure spoken dialogue in {language}. DO NOT leave it empty if the character is speaking!\n"
        f"4. Make sure `visual_prompt` is pure physical description in ENGLISH "
        f"with NO DIALOGUE text inside. Replace any dialogue in `visual_prompt` with silent actions.\n"
        f"5. Improve pacing (`duration_seconds`). VARY the durations narratively (e.g. 4 or 5 for dialogue/action, 7 or 8 for establishing shots). Do NOT leave every scene exactly the same length. The value MUST be a single number.\n"
        f"6. Improve camera usage — vary shot_type, movement, and angle "
        f"narratively; match them to mood and narrative_phase.\n"
        f"7. You MUST ensure there are EXACTLY {typical_scenes} scenes in the final script. If the draft has fewer, EXPAND the story. If it has more, KEEP them or combine them to reach exactly {typical_scenes}.\n"
        f"8. UPGRADE weak dialogue: replace any empty exclamation-only `audio_text` "
        f"('¡Sí!', '¡Pum!', '¡Gol!'…) with a real, meaningful line. Collapse extra "
        f"greeting/farewell scenes so at most ONE of each remains.\n\n"
        f"{_DIALOGUE_QUALITY}\n\n"
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

        # Enforce the same minimum scene floor as GenerateScript — the reviewer
        # must not shrink the script below the duration target.
        min_scenes, typical_scenes = _scene_count_targets(
            pod.config.duration_seconds, pod.config.max_clip_seconds
        )
        prompt = (
            f"{_REVIEW_SYSTEM}\n\n"
            + _render_review_prompt(
                draft_json=draft_json,
                language=pod.config.language,
                typical_scenes=typical_scenes,
            )
        )
        review_schema = copy.deepcopy(_SCENE_SCHEMA)
        review_schema["properties"]["scenes"]["minItems"] = min_scenes
        raw = await self.llm.complete(
            prompt, response_schema=review_schema, temperature=0.4,
        )
        try:
            data = json.loads(_clean_json(raw))
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON. Snippet: {raw[:100]}... Error: {exc}") from exc

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


@dataclass(frozen=True, slots=True)
class UpdateScriptScene:
    """Edit one scene's visual_prompt / audio_text before re-rendering it.

    Updates both the typed Scene field AND the engine-shaped `raw` dict (the
    render reads `raw`), so a subsequent render uses the new prompt/dialogue.
    """

    pod_repo: PodRepository
    script_repo: ScriptRepository

    async def execute(
        self, *, script_id: ScriptId, scene_index: int, requester_id: UserId,
        visual_prompt: str | None = None, audio_text: str | None = None,
    ) -> Script:
        script = await self.script_repo.get(script_id)
        if script is None:
            raise ScriptNotFound(f"script {script_id} not found")
        pod = await self.pod_repo.get(script.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("script belongs to a pod owned by a different user")
        if not 0 <= scene_index < len(script.scenes):
            raise ValidationError(
                f"scene_index {scene_index} out of range (0..{len(script.scenes) - 1})"
            )
        scene = script.scenes[scene_index]
        if visual_prompt is not None:
            scene.visual_prompt = visual_prompt
            scene.raw["visual_prompt"] = visual_prompt
        if audio_text is not None:
            scene.audio_text = audio_text
            scene.raw["audio_text"] = audio_text
        return await self.script_repo.save(script)


__all__ = [
    "DeleteScript", "GenerateScript", "ListScripts", "ReviewScript",
    "UpdateScriptScene", "WriteStory",
]
