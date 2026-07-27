"""Tests for the YouTube upload endpoint (routers/publish.py::youtube_upload).

The publisher *class* is covered by test_youtube_publisher.py; this exercises
the router glue: the missing-video guard, the SEO fallback for
description/tags, and persisting youtube_video_id on the episode. The router
function is called directly with fake container/use-case objects so no
FastAPI app, HTTP layer, network, or googleapiclient is involved.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from videocreator.domain.entities import Episode
from videocreator.infrastructure.publish import youtube_publisher as yt_module
from videocreator.infrastructure.publish.youtube_publisher import UploadResult
from videocreator.interfaces.rest.routers import publish as publish_router
from videocreator.interfaces.rest.schemas import YouTubeUploadRequest
from videocreator.shared.errors import NotFoundError, ValidationError
from videocreator.shared.ids import EpisodeId, PodId, UserId

OWNER = UserId("usr_1")


# ============================================================================
# Fakes
# ============================================================================
class _FakeStorage:
    """open_path returns a path; existence is controlled by `make_exist`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.opened: list[tuple[str, str]] = []

    async def open_path(self, bucket: str, key: str) -> Path:
        self.opened.append((bucket, key))
        return self._path


class _FakeOAuth:
    async def build_credentials(self, user_id: UserId) -> object:
        return object()  # opaque creds — the fake publisher ignores them


class _FakeEpisodeRepo:
    def __init__(self) -> None:
        self.saved: list[Episode] = []

    async def save(self, episode: Episode) -> Episode:
        self.saved.append(episode)
        return episode


class _FakeContainer:
    def __init__(self, *, storage: _FakeStorage, repo: _FakeEpisodeRepo) -> None:
        self._storage = storage
        self._repo = repo
        self._oauth = _FakeOAuth()

    def storage(self) -> _FakeStorage:
        return self._storage

    def youtube_oauth(self) -> _FakeOAuth:
        return self._oauth

    def episode_repo(self) -> _FakeEpisodeRepo:
        return self._repo


class _Resolver:
    """Mimics a use case with an `.execute(**kwargs)` coroutine method."""

    def __init__(self, result: Any, *, raises: Exception | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._result


class _Group:
    def __init__(self, get: _Resolver) -> None:
        self.get = get


class _FakeUseCases:
    def __init__(self, *, episode_get: _Resolver, seo_get: _Resolver) -> None:
        self.episodes = _Group(episode_get)
        self.seo = _Group(seo_get)


class _FakePublisher:
    """Records upload kwargs; returns a canned UploadResult."""

    last: dict[str, Any] = {}

    def __init__(self, credentials: Any = None) -> None:
        self.credentials = credentials

    def upload(self, path: Path, **kwargs: Any) -> UploadResult:
        type(self).last = {"path": path, **kwargs}
        return UploadResult(
            video_id="yt-zzz", url="https://www.youtube.com/watch?v=yt-zzz",
        )


class _Seo:
    def __init__(self, description: str | None, tags: list[str] | None) -> None:
        self.description = description
        self.tags = tags


# ============================================================================
# Builders / fixtures
# ============================================================================
def _episode(**over: Any) -> Episode:
    defaults: dict[str, Any] = dict(
        id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), title="Black Holes 101",
        number=1, final_video_key="ep_1/final.mp4",
    )
    defaults.update(over)
    return Episode(**defaults)


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "final.mp4"
    p.write_bytes(b"\x00\x00")
    return p


@pytest.fixture(autouse=True)
def _patch_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the real YouTubePublisher (built inside the router via a lazy
    import of this module) for a network-free fake."""
    _FakePublisher.last = {}
    monkeypatch.setattr(yt_module, "YouTubePublisher", _FakePublisher)


def _build(
    *, episode: Episode | None, video_path: Path, seo: _Seo | None,
    episode_raises: Exception | None = None,
) -> tuple[_FakeContainer, _FakeUseCases, _FakeEpisodeRepo, _FakeStorage]:
    repo = _FakeEpisodeRepo()
    storage = _FakeStorage(video_path)
    container = _FakeContainer(storage=storage, repo=repo)
    uc = _FakeUseCases(
        episode_get=_Resolver(episode, raises=episode_raises),
        seo_get=_Resolver(seo, raises=None if seo is not None else KeyError("none")),
    )
    return container, uc, repo, storage


# ============================================================================
# Tests
# ============================================================================
async def test_happy_path_uploads_and_saves_video_id(video_file: Path) -> None:
    # Arrange
    ep = _episode()
    container, uc, repo, _ = _build(episode=ep, video_path=video_file, seo=None)
    body = YouTubeUploadRequest(
        episode_id="ep_1", title="My Title", description="hello", tags=["a", "b"],
    )

    # Act
    resp = await publish_router.youtube_upload(body, container, uc, OWNER)

    # Assert — response surfaces the publisher result
    assert resp.video_id == "yt-zzz"
    assert resp.url == "https://www.youtube.com/watch?v=yt-zzz"
    # explicit body fields passed straight through to the publisher
    assert _FakePublisher.last["title"] == "My Title"
    assert _FakePublisher.last["description"] == "hello"
    assert _FakePublisher.last["tags"] == ("a", "b")
    assert _FakePublisher.last["privacy"] == "private"
    # youtube_video_id persisted on the episode
    assert len(repo.saved) == 1
    assert repo.saved[0].youtube_video_id == "yt-zzz"


async def test_missing_video_raises_validation_error(video_file: Path) -> None:
    # Arrange — episode has neither a dubbed nor a final video key
    ep = _episode(final_video_key=None, dubbed_video_key=None)
    container, uc, _, _ = _build(episode=ep, video_path=video_file, seo=None)
    body = YouTubeUploadRequest(episode_id="ep_1")

    # Act / Assert
    with pytest.raises(ValidationError, match="no rendered video"):
        await publish_router.youtube_upload(body, container, uc, OWNER)


async def test_missing_file_on_disk_raises_not_found(tmp_path: Path) -> None:
    # Arrange — key is set but the file does not exist on disk
    ep = _episode()
    missing = tmp_path / "ghost.mp4"
    container, uc, _, _ = _build(episode=ep, video_path=missing, seo=None)
    body = YouTubeUploadRequest(episode_id="ep_1")

    # Act / Assert
    with pytest.raises(NotFoundError):
        await publish_router.youtube_upload(body, container, uc, OWNER)


async def test_falls_back_to_seo_for_description_and_tags(video_file: Path) -> None:
    # Arrange — body omits description/tags; SEO metadata supplies them
    ep = _episode()
    seo = _Seo(description="from seo", tags=["space", "physics"])
    container, uc, _, _ = _build(episode=ep, video_path=video_file, seo=seo)
    body = YouTubeUploadRequest(episode_id="ep_1")  # no title/description/tags

    # Act
    await publish_router.youtube_upload(body, container, uc, OWNER)

    # Assert — title defaults to episode title; SEO fills the rest
    assert _FakePublisher.last["title"] == "Black Holes 101"
    assert _FakePublisher.last["description"] == "from seo"
    assert _FakePublisher.last["tags"] == ("space", "physics")


async def test_prefers_dubbed_video_key_over_final(video_file: Path) -> None:
    # Arrange — both keys present; router must select the dubbed one
    ep = _episode(final_video_key="ep_1/final.mp4", dubbed_video_key="ep_1/dub.mp4")
    container, uc, _, storage = _build(episode=ep, video_path=video_file, seo=None)
    body = YouTubeUploadRequest(episode_id="ep_1")

    # Act
    await publish_router.youtube_upload(body, container, uc, OWNER)

    # Assert — storage was asked for the dubbed key, not the final one
    assert storage.opened == [("episodes", "ep_1/dub.mp4")]


async def test_seo_failure_is_swallowed(video_file: Path) -> None:
    # Arrange — SEO lookup raises; router must degrade to empty description/tags
    ep = _episode()
    container, uc, _, _ = _build(episode=ep, video_path=video_file, seo=None)
    body = YouTubeUploadRequest(episode_id="ep_1")

    # Act
    resp = await publish_router.youtube_upload(body, container, uc, OWNER)

    # Assert — upload proceeds; missing SEO leaves description empty, tags empty
    assert resp.video_id == "yt-zzz"
    assert _FakePublisher.last["description"] == ""
    assert _FakePublisher.last["tags"] == ()
