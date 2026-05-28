"""ID generation helpers — ULID-like sortable IDs without external deps."""
from __future__ import annotations

import secrets
import time
from typing import NewType

PodId = NewType("PodId", str)
CharacterId = NewType("CharacterId", str)
TopicId = NewType("TopicId", str)
ScriptId = NewType("ScriptId", str)
EpisodeId = NewType("EpisodeId", str)
SceneId = NewType("SceneId", str)
ShortId = NewType("ShortId", str)
JobId = NewType("JobId", str)
UserId = NewType("UserId", str)
VariantId = NewType("VariantId", str)


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def _encode(num: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_ALPHABET[num & 0x1F])
        num >>= 5
    return "".join(reversed(chars))


def generate_id(prefix: str = "") -> str:
    """Return a sortable, URL-safe ID.

    Format: `<prefix>_<10-char-time><12-char-random>` (26 chars after prefix).
    Sort order matches creation time within a process.
    """
    ts_ms = int(time.time() * 1000)
    time_part = _encode(ts_ms, 10)
    random_part = _encode(secrets.randbits(60), 12)
    body = f"{time_part}{random_part}"
    return f"{prefix}_{body}" if prefix else body


def new_pod_id() -> PodId:
    return PodId(generate_id("pod"))


def new_character_id() -> CharacterId:
    return CharacterId(generate_id("chr"))


def new_topic_id() -> TopicId:
    return TopicId(generate_id("top"))


def new_script_id() -> ScriptId:
    return ScriptId(generate_id("scr"))


def new_episode_id() -> EpisodeId:
    return EpisodeId(generate_id("ep"))


def new_scene_id() -> SceneId:
    return SceneId(generate_id("scn"))


def new_short_id() -> ShortId:
    return ShortId(generate_id("sht"))


def new_job_id() -> JobId:
    return JobId(generate_id("job"))


def new_user_id() -> UserId:
    return UserId(generate_id("usr"))


def new_variant_id() -> VariantId:
    return VariantId(generate_id("var"))
