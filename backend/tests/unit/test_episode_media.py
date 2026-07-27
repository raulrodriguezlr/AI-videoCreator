"""Tests for the storage-backed media library.

Every artifact is read from the object store under episodes/<id>/<rel>; the
library classifies by extension and emits /storage URLs.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from videocreator.domain.entities import Episode
from videocreator.infrastructure.media.library import EPISODE_BUCKET, LocalMediaLibrary
from videocreator.shared.ids import EpisodeId, PodId


class _FakeStorage:
    def __init__(self, keys: dict[str, bytes]) -> None:
        self.objects = keys

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        assert bucket == EPISODE_BUCKET
        return [k for k in self.objects if k.startswith(prefix)]

    # unused port methods
    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str: return key
    async def get(self, bucket: str, key: str) -> bytes: return b""
    async def open_path(self, bucket: str, key: str) -> Path: return Path(key)
    async def delete(self, bucket: str, key: str) -> None: ...
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str: return key


def _episode() -> Episode:
    return Episode(id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), title="Ep", number=1)


async def test_lists_and_classifies_storage_media() -> None:
    storage = _FakeStorage({
        "ep_1/clips/clip_01.mp4": b"v",
        "ep_1/audio/dialogue_01.wav": b"a",
        "ep_1/frames/frame_01.png": b"i",
        "ep_1/script.json": b"{}",       # non-media, ignored
        "ep_2/clips/other.mp4": b"x",     # other episode, ignored
    })
    lib = LocalMediaLibrary(storage)  # type: ignore[arg-type]

    assets = await lib.list_for_episode(_episode())

    assert sorted(a.kind for a in assets) == ["audio", "image", "video"]


async def test_media_url_points_at_storage_proxy() -> None:
    storage = _FakeStorage({"ep_1/clips/clip_01.mp4": b"v"})
    lib = LocalMediaLibrary(storage)  # type: ignore[arg-type]

    asset = (await lib.list_for_episode(_episode()))[0]

    assert asset.url == "/api/v1/storage/episodes/ep_1/clips/clip_01.mp4"
    assert asset.group == "clips"
    assert asset.content_type == "video/mp4"


async def test_episode_without_media_is_empty() -> None:
    lib = LocalMediaLibrary(_FakeStorage({}))  # type: ignore[arg-type]
    assert await lib.list_for_episode(_episode()) == []
