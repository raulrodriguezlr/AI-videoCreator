"""One-shot importer for legacy filesystem pods.

Reads `pods/<name>/config.json` etc. and creates Pod + Character entities
under the local user. Idempotent: re-running updates existing pods rather
than duplicating.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.domain.entities import (
    LOCAL_USER_ID,
    Character,
    Pod,
    PodConfig,
    Topic,
)
from videocreator.domain.ports import (
    CharacterRepository,
    PodRepository,
    TopicRepository,
)
from videocreator.domain.value_objects import (
    ProviderPreferences,
    StyleProfile,
    TopicStatus,
    VoiceSettings,
)
from videocreator.shared.ids import (
    PodId,
    new_character_id,
    new_pod_id,
    new_topic_id,
)
from videocreator.shared.logging import get_logger
from videocreator.shared.time import utcnow

log = get_logger(__name__)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("legacy.invalid_json", path=str(path))
        return None


def _style_from_config(data: dict[str, Any]) -> StyleProfile:
    style_str = (data.get("consistency", {}) or {}).get("art_style", "")
    if not isinstance(style_str, str):
        return StyleProfile.CINEMATIC_3D
    lowered = style_str.lower()
    if "anime" in lowered:
        return StyleProfile.ANIME_2D
    if "kids" in lowered or "disney" in lowered or "pixar" in lowered:
        return StyleProfile.KIDS_3D
    if "documentary" in lowered or "documental" in lowered:
        return StyleProfile.PHOTOREAL_DOC
    return StyleProfile.CINEMATIC_3D


async def import_legacy_pod(
    pod_dir: Path,
    *,
    pod_repo: PodRepository,
    char_repo: CharacterRepository,
    topic_repo: TopicRepository,
) -> Pod | None:
    config_path = pod_dir / "config.json"
    config_data = _read_json(config_path)
    if config_data is None:
        log.info("legacy.skip_no_config", pod_dir=str(pod_dir))
        return None

    pod_name = pod_dir.name
    existing = [p for p in await pod_repo.list_for_user(LOCAL_USER_ID) if p.name == pod_name]
    pod_id: PodId = existing[0].id if existing else new_pod_id()

    pod_config = PodConfig(
        series_name=config_data.get("series_name", pod_name),
        target_audience=config_data.get("target_audience", "general"),
        language=config_data.get("language", "es"),
        art_style=(config_data.get("consistency") or {}).get("art_style"),
        style_profile=_style_from_config(config_data),
        duration_seconds=int((config_data.get("video_settings") or {}).get("duration_seconds", 120)),
        provider_preferences=ProviderPreferences(),
        series_context=config_data.get("series_context"),
        extra={k: v for k, v in config_data.items() if k not in {
            "series_name", "target_audience", "language", "consistency",
            "video_settings", "series_context", "characters",
        }},
    )

    pod = Pod(
        id=pod_id,
        owner_id=LOCAL_USER_ID,
        name=pod_name,
        config=pod_config,
        created_at=existing[0].created_at if existing else utcnow(),
    )
    await pod_repo.save(pod)
    log.info("legacy.pod_imported", pod=pod_name, pod_id=pod.id)

    # Characters
    existing_chars = {c.name: c for c in await char_repo.list_for_pod(pod.id)}
    for char_data in (config_data.get("characters") or []):
        if not isinstance(char_data, dict):
            continue
        name = char_data.get("name") or "unnamed"
        existing_char = existing_chars.get(name)
        voice_id = char_data.get("elevenlabs_voice_id")
        voice_kwargs = char_data.get("elevenlabs_voice_settings") or {}
        voice = (
            VoiceSettings(voice_id=voice_id, **{
                k: v for k, v in voice_kwargs.items() if k in VoiceSettings.model_fields
            })
            if voice_id
            else None
        )
        character = Character(
            id=existing_char.id if existing_char else new_character_id(),
            pod_id=pod.id,
            name=name,
            role=char_data.get("role", "supporting"),
            personality=char_data.get("personality"),
            look_description=char_data.get("look_description"),
            voice=voice,
            reference_image_keys=[],  # uploaded separately below
        )
        await char_repo.save(character)

    # Topics
    topics_data = _read_json(pod_dir / "topics.json") or {}
    for raw in (topics_data.get("topics") or []):
        if not isinstance(raw, dict):
            continue
        topic = Topic(
            id=new_topic_id(),
            pod_id=pod.id,
            title=raw.get("title", "untitled"),
            description=raw.get("description"),
            status=TopicStatus(raw.get("status", "pending")) if raw.get("status") in {
                s.value for s in TopicStatus
            } else TopicStatus.PENDING,
            educational_value=raw.get("educational_value"),
        )
        await topic_repo.save(topic)

    return pod


async def import_all_legacy_pods(
    pods_root: Path,
    *,
    pod_repo: PodRepository,
    char_repo: CharacterRepository,
    topic_repo: TopicRepository,
) -> list[Pod]:
    if not pods_root.exists():
        return []
    imported: list[Pod] = []
    for entry in sorted(pods_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        result = await import_legacy_pod(
            entry, pod_repo=pod_repo, char_repo=char_repo, topic_repo=topic_repo
        )
        if result is not None:
            imported.append(result)
    return imported
