"""Unit tests for the local gameplay b-roll library (indexing, rotation,
composite fallback, Pexels populate) — no ffmpeg/network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from videocreator.infrastructure.media.gameplay_broll import (
    CompositeBrollLibrary,
    GameplayBrollLibrary,
    populate_from_pexels,
)


@pytest.fixture()
def gameplay_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "gameplay"
    d.mkdir()
    (d / "minecraft_01.mp4").write_bytes(b"fake-mp4-1")
    (d / "gta_01.mp4").write_bytes(b"fake-mp4-2")
    (d / "not_a_video.txt").write_text("ignore me")
    # Avoid shelling out to real ffprobe in unit tests.
    monkeypatch.setattr(
        "videocreator.infrastructure.media.gameplay_broll.probe_duration_s",
        lambda path: 42.0,
    )
    return d


# ---- indexing ---------------------------------------------------------------
def test_list_clips_only_indexes_video_files(gameplay_dir: Path) -> None:
    lib = GameplayBrollLibrary(gameplay_dir)
    clips = lib.list_clips()
    names = {c.name for c in clips}
    assert names == {"minecraft_01.mp4", "gta_01.mp4"}
    assert all(c.duration_s == 42.0 for c in clips)


def test_list_clips_empty_folder(tmp_path: Path) -> None:
    lib = GameplayBrollLibrary(tmp_path / "missing")
    assert lib.list_clips() == []
    assert lib.is_empty


def test_duration_cache_avoids_reprobing(gameplay_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _probe(path: Path) -> float:
        calls["n"] += 1
        return 10.0

    monkeypatch.setattr(
        "videocreator.infrastructure.media.gameplay_broll.probe_duration_s", _probe
    )
    lib = GameplayBrollLibrary(gameplay_dir)
    lib.list_clips()
    lib.list_clips()
    assert calls["n"] == 2  # one probe per file, second listing is cached


def test_attribution_sidecar_is_read(gameplay_dir: Path) -> None:
    side = gameplay_dir / "minecraft_01.mp4.attribution.json"
    side.write_text(json.dumps({"source": "pexels", "author": "Jane"}), encoding="utf-8")
    lib = GameplayBrollLibrary(gameplay_dir)
    clip = next(c for c in lib.list_clips() if c.name == "minecraft_01.mp4")
    assert clip.attribution == {"source": "pexels", "author": "Jane"}


# ---- rotation -----------------------------------------------------------------
def test_next_clip_round_robins_without_repeat(gameplay_dir: Path) -> None:
    lib = GameplayBrollLibrary(gameplay_dir)
    first = lib.next_clip()
    second = lib.next_clip()
    third = lib.next_clip()  # wraps back around
    assert first is not None and second is not None
    assert first.name != second.name
    assert third.name == first.name


def test_rotation_persists_across_instances(gameplay_dir: Path) -> None:
    lib1 = GameplayBrollLibrary(gameplay_dir)
    picked_first = lib1.next_clip()
    lib2 = GameplayBrollLibrary(gameplay_dir)  # fresh instance, same folder
    picked_second = lib2.next_clip()
    assert picked_first is not None and picked_second is not None
    assert picked_first.name != picked_second.name


def test_next_clip_empty_folder_returns_none(tmp_path: Path) -> None:
    lib = GameplayBrollLibrary(tmp_path / "empty")
    assert lib.next_clip() is None


# ---- CC0BrollLibrary-compatible fetch() ----------------------------------------
async def test_fetch_returns_media_asset(gameplay_dir: Path) -> None:
    lib = GameplayBrollLibrary(gameplay_dir)
    asset = await lib.fetch("satisfying")
    assert asset is not None
    assert asset.kind == "video"
    assert asset.path.parent == gameplay_dir


async def test_fetch_empty_folder_returns_none(tmp_path: Path) -> None:
    lib = GameplayBrollLibrary(tmp_path / "empty")
    assert await lib.fetch("satisfying") is None


# ---- composite: local-first, remote fallback -----------------------------------
async def test_composite_prefers_local_when_available(gameplay_dir: Path) -> None:
    remote = MagicMock()
    remote.fetch = AsyncMock(return_value="SHOULD_NOT_BE_USED")
    composite = CompositeBrollLibrary(GameplayBrollLibrary(gameplay_dir), remote)
    asset = await composite.fetch("satisfying")
    assert asset is not None
    assert asset != "SHOULD_NOT_BE_USED"
    remote.fetch.assert_not_called()


async def test_composite_falls_back_to_remote_when_local_empty(tmp_path: Path) -> None:
    remote = MagicMock()
    remote.fetch = AsyncMock(return_value="REMOTE_ASSET")
    composite = CompositeBrollLibrary(GameplayBrollLibrary(tmp_path / "empty"), remote)
    asset = await composite.fetch("satisfying", max_duration_s=30.0)
    assert asset == "REMOTE_ASSET"
    remote.fetch.assert_awaited_once_with("satisfying", max_duration_s=30.0)


async def test_composite_no_remote_configured(tmp_path: Path) -> None:
    composite = CompositeBrollLibrary(GameplayBrollLibrary(tmp_path / "empty"), None)
    assert await composite.fetch("satisfying") is None


# ---- populate from Pexels (mocked httpx, no real network/downloads) -----------
async def test_populate_from_pexels_requires_api_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PEXELS_API_KEY"):
        await populate_from_pexels(tmp_path, api_key="")


async def test_populate_from_pexels_downloads_and_writes_attribution(tmp_path: Path) -> None:
    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json = MagicMock(return_value={
        "videos": [{
            "id": 123,
            "url": "https://pexels.com/video/123",
            "user": {"name": "Jane Doe"},
            "video_files": [
                {"file_type": "video/mp4", "height": 1920, "link": "https://cdn.pexels.com/v.mp4"},
            ],
        }]
    })
    download_response = MagicMock()
    download_response.raise_for_status = MagicMock()
    download_response.content = b"fake-video-bytes"

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[search_response, download_response] * 10)

    clips = await populate_from_pexels(
        tmp_path, api_key="fake-key", count=1, http_client=fake_client,
    )

    assert len(clips) == 1
    assert clips[0].author == "Jane Doe"
    downloaded_files = list(tmp_path.glob("*.mp4"))
    assert len(downloaded_files) == 1
    sidecar = downloaded_files[0].with_suffix(".mp4.attribution.json")
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["source"] == "pexels"
    assert data["author"] == "Jane Doe"
    # Never touched the real network — only our fake client was called.
    fake_client.aclose.assert_not_called()  # client was injected, not owned


async def test_populate_from_pexels_skips_query_with_no_results(tmp_path: Path) -> None:
    empty_response = MagicMock()
    empty_response.raise_for_status = MagicMock()
    empty_response.json = MagicMock(return_value={"videos": []})
    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=empty_response)

    clips = await populate_from_pexels(
        tmp_path, api_key="fake-key", count=3, http_client=fake_client,
    )
    assert clips == []
