"""Importer for filesystem content pods.

Reads `pods/<name>/config.json` etc. and creates Pod + Character entities
under the local user. Idempotent: re-running updates existing pods rather
than duplicating.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from videocreator.domain.entities import (
    LOCAL_USER_ID,
    Character,
    Episode,
    Pod,
    PodConfig,
    Scene,
    Script,
    SeoMetadata,
    Topic,
)
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    PodRepository,
    ScriptRepository,
    SeoRepository,
    StoragePort,
    TopicRepository,
)
from videocreator.domain.value_objects import (
    EpisodeState,
    ProviderPreferences,
    StyleProfile,
    TopicStatus,
    VoiceSettings,
)
from videocreator.shared.ids import (
    PodId,
    ScriptId,
    new_character_id,
    new_episode_id,
    new_pod_id,
    new_scene_id,
    new_script_id,
    new_seo_id,
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
        log.warning("pods.invalid_json", path=str(path))
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


# The `metadata.json["status"]` → domain EpisodeState. An episode with a
# full output/ tree is effectively a finished render, so the common "created"
# maps to READY rather than DRAFT.
_STATUS_TO_STATE: dict[str, EpisodeState] = {
    "created": EpisodeState.READY,
    "ready": EpisodeState.READY,
    "rendering": EpisodeState.RENDERING,
    "failed": EpisodeState.FAILED,
    "published": EpisodeState.PUBLISHED,
}
_HASHTAG_RE = re.compile(r"#(\w+)")
_EP_NUMBER_RE = re.compile(r"ep[_-]?(\d+)", re.IGNORECASE)


def _infer_episode_number(folder_name: str) -> int:
    match = _EP_NUMBER_RE.search(folder_name)
    return int(match.group(1)) if match else 1


async def _import_episode_seo(
    *, episode: Episode, pod: Pod, yt: dict[str, Any], seo_repo: SeoRepository,
) -> None:
    """Project a `youtube_metadata.json` into a SeoMetadata record."""
    title = str(yt.get("titulo_youtube") or "").strip()
    description = str(yt.get("descripcion_youtube") or "").strip()
    hashtags = [f"#{tag}" for tag in _HASHTAG_RE.findall(description)]
    existing = await seo_repo.get_for_episode(episode.id)
    metadata = SeoMetadata(
        id=existing.id if existing else new_seo_id(),
        pod_id=pod.id,
        episode_id=episode.id,
        description=description,
        hashtags=hashtags,
        title_variants=[title] if title else [],
        selected_title=title or None,
        created_at=existing.created_at if existing else episode.created_at,
    )
    await seo_repo.save(metadata)


# Reference-image bucket (shared with the asset manager).
_REF_BUCKET = "references"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_TRANSITIONS = {"continue", "cut", "scene_change"}


def _norm(text: str) -> str:
    """Lowercase + strip non-alphanumerics — for fuzzy name/file matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _scene_from_raw(raw: dict[str, Any], index: int) -> Scene:
    camera = raw.get("camera")
    shot = movement = angle = None
    if isinstance(camera, dict):
        shot = camera.get("shot") or camera.get("type")
        movement = camera.get("movement")
        angle = camera.get("angle")
    elif isinstance(camera, str):
        shot = camera
    transition = str(raw.get("transition_to_next") or "cut").lower()
    return Scene(
        id=new_scene_id(),
        index=int(raw.get("scene_number") or index + 1),
        visual_prompt=str(raw.get("visual_prompt") or ""),
        audio_text=raw.get("audio_text"),
        transition=transition if transition in _TRANSITIONS else "cut",  # type: ignore[arg-type]
        duration_s=float(raw.get("duration_seconds") or 8.0),
        camera_shot=shot,
        camera_movement=movement,
        camera_angle=angle,
        raw=dict(raw),  # preserve the full engine-shaped scene for faithful renders
    )


async def _import_episode_script(
    *, ep_dir: Path, episode: Episode, pod: Pod, prev_script_id: str | None,
    script_repo: ScriptRepository,
) -> str | None:
    """Project a `script.json` into a Script; return its id."""
    data = _read_json(ep_dir / "script.json")
    if not data:
        return None
    raw_scenes = data.get("scenes") if isinstance(data, dict) else None
    scenes = [
        _scene_from_raw(s, i)
        for i, s in enumerate(raw_scenes or [])
        if isinstance(s, dict)
    ]
    script = Script(
        id=ScriptId(prev_script_id) if prev_script_id else new_script_id(),
        pod_id=pod.id,
        topic_id=episode.topic_id,
        title=str(data.get("title") or episode.title),
        summary=data.get("summary") or data.get("moral"),
        scenes=scenes,
        reviewed=True,  # imported scripts are already produced
        created_at=episode.created_at,
    )
    await script_repo.save(script)
    return script.id


async def import_assets(
    pod: Pod, pod_dir: Path, *, char_repo: CharacterRepository, storage: StoragePort,
) -> int:
    """Attach images in `assets/` to characters by fuzzy name match.

    `ref_tico.png` → the character named "Tico". Idempotent: an asset already
    attached (same filename) is skipped.
    """
    assets_dir = pod_dir / "assets"
    if not assets_dir.exists():
        return 0
    characters = await char_repo.list_for_pod(pod.id)
    if not characters:
        return 0

    attached = 0
    for asset in sorted(assets_dir.iterdir()):
        if not asset.is_file() or asset.suffix.lower() not in _IMAGE_EXTS:
            continue
        stem = _norm(asset.stem)
        match = next((c for c in characters if c.name and _norm(c.name) in stem), None)
        if match is None:
            continue
        if any(ref.endswith(f"/{asset.name}") for ref in match.reference_image_keys):
            continue  # already imported
        key = f"{pod.id}/{match.id}/{asset.name}"
        ref = await storage.put(_REF_BUCKET, key, asset.read_bytes())
        match.reference_image_keys.append(ref)
        await char_repo.save(match)
        attached += 1

    if attached:
        log.info("pods.assets_imported", pod=pod.name, count=attached)
    return attached


_MEDIA_INGEST_EXTS = {
    ".mp4", ".mov", ".webm", ".mkv", ".m4v",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
}


async def _ingest_episode_media(episode: Episode, ep_dir: Path, storage: StoragePort) -> int:
    """Copy an episode's on-disk media into the object store, once.

    Files land at ``episodes/<episode_id>/<relpath>`` so the media library and
    the API serve everything from storage — the source `pods/` tree is never
    read again. Idempotent: keys already present are skipped.
    """
    from videocreator.infrastructure.media.library import EPISODE_BUCKET

    existing = set(await storage.list_keys(EPISODE_BUCKET, prefix=f"{episode.id}/"))
    copied = 0
    for path in sorted(ep_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _MEDIA_INGEST_EXTS:
            continue
        key = f"{episode.id}/{path.relative_to(ep_dir).as_posix()}"
        if key in existing:
            continue
        await storage.put(EPISODE_BUCKET, key, path.read_bytes())
        copied += 1
    return copied


async def import_episodes(
    pod: Pod,
    pod_dir: Path,
    *,
    episode_repo: EpisodeRepository,
    seo_repo: SeoRepository,
    topic_repo: TopicRepository,
    script_repo: ScriptRepository | None = None,
    storage: StoragePort | None = None,
) -> int:
    """Create Episode records from each `output/ep_*/` directory and ingest its
    media into the object store.

    Idempotent: episodes are matched by `extra["media_dir"]` and media files
    already in storage are skipped, so re-runs update in place.
    """
    output_dir = pod_dir / "output"
    if not output_dir.exists():
        return 0

    existing_eps = await episode_repo.list_for_pod(pod.id)
    by_dir = {
        e.extra.get("media_dir"): e for e in existing_eps if e.extra.get("media_dir")
    }
    topics_by_title = {
        t.title.strip().lower(): t.id for t in await topic_repo.list_for_pod(pod.id)
    }

    imported = 0
    for ep_dir in sorted(output_dir.iterdir()):
        if not ep_dir.is_dir() or ep_dir.name.startswith(("_", ".")):
            continue
        meta = _read_json(ep_dir / "metadata.json") or {}
        title = str(meta.get("title") or meta.get("topic") or ep_dir.name)
        number = int(meta.get("episode_number") or _infer_episode_number(ep_dir.name))
        status_key = str(meta.get("status") or "created").lower()
        state = _STATUS_TO_STATE.get(status_key, EpisodeState.READY)
        prev = by_dir.get(ep_dir.name)
        topic_id = topics_by_title.get(str(meta.get("topic") or "").strip().lower())

        episode = Episode(
            id=prev.id if prev else new_episode_id(),
            pod_id=pod.id,
            topic_id=topic_id,
            script_id=prev.script_id if prev else None,
            title=title,
            number=number,
            state=state,
            created_at=prev.created_at if prev else pod.created_at,
            extra={
                "media_pod": pod_dir.name,
                "media_dir": ep_dir.name,
                "total_scenes": meta.get("total_scenes"),
                "topic": meta.get("topic"),
                "imported_at": meta.get("created_at"),
            },
        )
        # Script (sets episode.script_id so the workspace can show + edit it).
        if script_repo is not None:
            script_id = await _import_episode_script(
                ep_dir=ep_dir, episode=episode, pod=pod,
                prev_script_id=prev.script_id if prev else None,
                script_repo=script_repo,
            )
            if script_id:
                episode.script_id = ScriptId(script_id)

        await episode_repo.save(episode)
        imported += 1

        if storage is not None:
            await _ingest_episode_media(episode, ep_dir, storage)

        yt = _read_json(ep_dir / "youtube_metadata.json")
        if yt:
            await _import_episode_seo(episode=episode, pod=pod, yt=yt, seo_repo=seo_repo)

    log.info("pods.episodes_imported", pod=pod.name, count=imported)
    return imported


async def import_pod_directory(
    pod_dir: Path,
    *,
    pod_repo: PodRepository,
    char_repo: CharacterRepository,
    topic_repo: TopicRepository,
    episode_repo: EpisodeRepository | None = None,
    seo_repo: SeoRepository | None = None,
    script_repo: ScriptRepository | None = None,
    storage: StoragePort | None = None,
) -> Pod | None:
    config_path = pod_dir / "config.json"
    config_data = _read_json(config_path)
    if config_data is None:
        log.info("pods.skip_no_config", pod_dir=str(pod_dir))
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
        duration_seconds=int(
            (config_data.get("video_settings") or {}).get("duration_seconds", 120)
        ),
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
    log.info("pods.pod_imported", pod=pod_name, pod_id=pod.id)

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

    # Topics — idempotent: match existing by title so re-imports never duplicate.
    topics_data = _read_json(pod_dir / "topics.json") or {}
    existing_topics = {
        t.title.strip().lower(): t for t in await topic_repo.list_for_pod(pod.id)
    }
    valid_status = {s.value for s in TopicStatus}
    for raw in (topics_data.get("topics") or []):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "untitled"))
        prev = existing_topics.get(title.strip().lower())
        status = raw.get("status", "pending")
        topic = Topic(
            id=prev.id if prev else new_topic_id(),
            pod_id=pod.id,
            title=title,
            description=raw.get("description"),
            status=TopicStatus(status) if status in valid_status else TopicStatus.PENDING,
            educational_value=raw.get("educational_value"),
            created_at=prev.created_at if prev else utcnow(),
        )
        await topic_repo.save(topic)

    # Reference images from assets/ — attach to characters by name match.
    if storage is not None:
        await import_assets(pod, pod_dir, char_repo=char_repo, storage=storage)

    # Episodes (+ their scripts + SEO) — only when the repos are provided.
    if episode_repo is not None and seo_repo is not None:
        await import_episodes(
            pod, pod_dir,
            episode_repo=episode_repo, seo_repo=seo_repo, topic_repo=topic_repo,
            script_repo=script_repo, storage=storage,
        )

    return pod


async def import_pods_from_disk(
    pods_root: Path,
    *,
    pod_repo: PodRepository,
    char_repo: CharacterRepository,
    topic_repo: TopicRepository,
    episode_repo: EpisodeRepository | None = None,
    seo_repo: SeoRepository | None = None,
    script_repo: ScriptRepository | None = None,
    storage: StoragePort | None = None,
) -> list[Pod]:
    if not pods_root.exists():
        return []
    imported: list[Pod] = []
    for entry in sorted(pods_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        result = await import_pod_directory(
            entry,
            pod_repo=pod_repo,
            char_repo=char_repo,
            topic_repo=topic_repo,
            episode_repo=episode_repo,
            seo_repo=seo_repo,
            script_repo=script_repo,
            storage=storage,
        )
        if result is not None:
            imported.append(result)
    return imported
