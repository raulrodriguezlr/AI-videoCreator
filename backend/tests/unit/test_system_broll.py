"""Tests for the gameplay b-roll endpoints (system router): list + populate.

Calls the router functions directly with a real Container (pointed at a tmp
var_dir), same pattern as test_system_recommend.py. Pexels download is mocked
via an injected http_client — never touches the network.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from videocreator.infrastructure.container import Container
from videocreator.interfaces.rest.routers.system import list_broll, populate_broll
from videocreator.interfaces.rest.schemas import PopulateBrollRequest
from videocreator.shared.config import Settings


def _settings(tmp_path: Path, **o: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "storage_url": "file://./var/storage",
        "var_dir": tmp_path / "var",
    }
    base.update(o)
    return Settings(**base)  # type: ignore[arg-type]


async def test_list_broll_empty_folder(tmp_path: Path) -> None:
    c = Container(_settings(tmp_path))
    res = await list_broll(c)
    assert res.clips == []
    assert res.folder.endswith(str(Path("broll") / "gameplay"))


async def test_list_broll_indexes_dropped_clips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = Container(_settings(tmp_path))
    lib = c.gameplay_broll_library()
    lib.folder.mkdir(parents=True, exist_ok=True)
    (lib.folder / "parkour.mp4").write_bytes(b"fake")
    monkeypatch.setattr(
        "videocreator.infrastructure.media.gameplay_broll.probe_duration_s",
        lambda path: 12.5,
    )
    res = await list_broll(c)
    assert len(res.clips) == 1
    assert res.clips[0].name == "parkour.mp4"
    assert res.clips[0].duration_s == 12.5


async def test_populate_broll_without_api_key_returns_422_with_instructions(tmp_path: Path) -> None:
    c = Container(_settings(tmp_path, pexels_api_key=""))
    with pytest.raises(HTTPException) as exc:
        await populate_broll(PopulateBrollRequest(), c, c.settings)
    assert exc.value.status_code == 422
    assert "pexels.com/api" in exc.value.detail


async def test_populate_broll_downloads_via_mocked_httpx(tmp_path: Path) -> None:
    c = Container(_settings(tmp_path, pexels_api_key="fake-key"))

    search_response = MagicMock()
    search_response.raise_for_status = MagicMock()
    search_response.json = MagicMock(return_value={
        "videos": [{
            "id": 1,
            "url": "https://pexels.com/video/1",
            "user": {"name": "Jane Doe"},
            "video_files": [
                {"file_type": "video/mp4", "height": 1920, "link": "https://cdn.pexels.com/v.mp4"},
            ],
        }]
    })
    download_response = MagicMock()
    download_response.raise_for_status = MagicMock()
    download_response.content = b"fake-bytes"

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[search_response, download_response] * 10)
    fake_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=fake_client):
        res = await populate_broll(PopulateBrollRequest(count=1), c, c.settings)

    assert len(res.downloaded) == 1
    assert res.downloaded[0].author == "Jane Doe"
    assert res.downloaded[0].source == "pexels"
    # The clip actually landed in the gameplay folder used by list_broll too.
    listing = await list_broll(c)
    assert len(listing.clips) == 1
