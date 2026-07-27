"""Tests for the legacy filesystem-pod importer, focused on the episode +
SEO projection added so old `output/ep_*/` renders surface in the new system.

Uses a real in-memory SQLite (StaticPool) so the SQL repos are exercised, and
a hermetic temp pod tree so the test never depends on the checked-in pods/.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from videocreator.domain.entities import make_local_user
from videocreator.domain.value_objects import EpisodeState
from videocreator.infrastructure.filesystem.pod_importer import import_pods_from_disk
from videocreator.infrastructure.persistence import models  # noqa: F401 — registers tables
from videocreator.infrastructure.persistence.database import Base
from videocreator.infrastructure.repositories.sql_repos import (
    SqlCharacterRepository,
    SqlEpisodeRepository,
    SqlPodRepository,
    SqlScriptRepository,
    SqlSeoRepository,
    SqlTopicRepository,
    SqlUserRepository,
)
from videocreator.infrastructure.storage.file_storage import LocalFileStorage


async def _make_sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_legacy_pod(root: Path) -> Path:
    """Create a minimal legacy pod tree with one episode + media + youtube meta."""
    pod = root / "kids_story"
    _write_json(pod / "config.json", {
        "series_name": "Las Aventuras de Tico",
        "language": "es",
        "characters": [{"name": "Tico", "role": "lead"}],
    })
    _write_json(pod / "topics.json", {"topics": [
        {"title": "El Misterio de las Bellotas", "description": "x"},
    ]})
    # A character-named asset to exercise reference-image matching.
    (pod / "assets").mkdir(parents=True, exist_ok=True)
    (pod / "assets" / "ref_tico.png").write_bytes(b"\x89PNG\x00")
    ep = pod / "output" / "ep_001_el_misterio_de_las_bellotas"
    _write_json(ep / "metadata.json", {
        "episode_number": 1,
        "title": "El Misterio de las Bellotas",
        "topic": "El Misterio de las Bellotas",
        "total_scenes": 19,
        "status": "created",
    })
    _write_json(ep / "youtube_metadata.json", {
        "titulo_youtube": "¡El Gran Misterio de las Bellotas!",
        "descripcion_youtube": "Una aventura. #CuentosInfantiles #TicoLaArdilla",
    })
    _write_json(ep / "script.json", {
        "title": "El Misterio de las Bellotas",
        "summary": "Tico busca sus bellotas.",
        "scenes": [
            {"scene_number": 1, "visual_prompt": "Tico waves", "audio_text": "¡Hola!",
             "duration_seconds": 6, "transition_to_next": "cut"},
            {"scene_number": 2, "visual_prompt": "Tico searches", "audio_text": "¿Dónde están?",
             "duration_seconds": 8, "camera": {"shot": "wide", "movement": "pan"}},
        ],
    })
    (ep / "clips").mkdir(parents=True, exist_ok=True)
    (ep / "clips" / "clip_01.mp4").write_bytes(b"\x00\x00")
    return root


async def _import(tmp_path: Path):  # type: ignore[no-untyped-def]
    sm = await _make_sessionmaker()
    await SqlUserRepository(sm).save(make_local_user())
    pods_root = _build_legacy_pod(tmp_path / "pods")
    pods = await import_pods_from_disk(
        pods_root,
        pod_repo=SqlPodRepository(sm),
        char_repo=SqlCharacterRepository(sm),
        topic_repo=SqlTopicRepository(sm),
        episode_repo=SqlEpisodeRepository(sm),
        seo_repo=SqlSeoRepository(sm),
        script_repo=SqlScriptRepository(sm),
        storage=LocalFileStorage(tmp_path / "storage"),
    )
    return sm, pods


async def test_imports_episodes_from_output_dirs(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)

    episodes = await SqlEpisodeRepository(sm).list_for_pod(pods[0].id)

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.number == 1
    assert ep.title == "El Misterio de las Bellotas"
    assert ep.state == EpisodeState.READY  # "created" → finished render
    assert bool(ep.extra.get("media_dir"))
    assert ep.extra["media_dir"] == "ep_001_el_misterio_de_las_bellotas"


async def test_links_episode_to_topic_by_title(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)

    ep = (await SqlEpisodeRepository(sm).list_for_pod(pods[0].id))[0]

    assert ep.topic_id is not None  # matched the seeded topic by title


async def test_imports_script_and_links_episode(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)

    ep = (await SqlEpisodeRepository(sm).list_for_pod(pods[0].id))[0]
    assert ep.script_id is not None

    script = await SqlScriptRepository(sm).get(ep.script_id)
    assert script is not None
    assert len(script.scenes) == 2
    assert script.scenes[0].audio_text == "¡Hola!"
    assert script.scenes[1].camera_shot == "wide"  # parsed from camera dict


async def test_imports_named_asset_as_character_reference(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)

    chars = await SqlCharacterRepository(sm).list_for_pod(pods[0].id)
    tico = next(c for c in chars if c.name == "Tico")

    assert len(tico.reference_image_keys) == 1
    assert tico.reference_image_keys[0].endswith("ref_tico.png")


async def test_imports_youtube_metadata_as_seo(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)

    ep = (await SqlEpisodeRepository(sm).list_for_pod(pods[0].id))[0]
    seo = await SqlSeoRepository(sm).get_for_episode(ep.id)

    assert seo is not None
    assert seo.selected_title == "¡El Gran Misterio de las Bellotas!"
    assert "#CuentosInfantiles" in seo.hashtags
    assert "#TicoLaArdilla" in seo.hashtags


async def test_reimport_is_idempotent(tmp_path: Path) -> None:
    sm, pods = await _import(tmp_path)
    repo = SqlEpisodeRepository(sm)
    first = await repo.list_for_pod(pods[0].id)

    # Re-run the import against the same DB + tree.
    pods_root = tmp_path / "pods"
    await import_pods_from_disk(
        pods_root,
        pod_repo=SqlPodRepository(sm),
        char_repo=SqlCharacterRepository(sm),
        topic_repo=SqlTopicRepository(sm),
        episode_repo=repo,
        seo_repo=SqlSeoRepository(sm),
    )
    second = await repo.list_for_pod(pods[0].id)

    assert len(second) == len(first) == 1
    assert second[0].id == first[0].id  # same episode reused, not duplicated
