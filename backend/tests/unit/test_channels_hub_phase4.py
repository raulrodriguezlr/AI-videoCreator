"""Phase-4 Channels Hub tests: TikTok publish-status polling, Instagram public-URL
publish flow, account health verification, and the Instagram enqueue guard.

Everything network-facing is injected with fakes — no real HTTP, no sleeping.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from videocreator.domain.entities import PublishAccount
from videocreator.domain.value_objects import AccountStatus, PublishPlatform, PublishStatus
from videocreator.infrastructure.publish.channel_accounts import (
    SECRET_ACCESS,
    SECRET_IG_USER_ID,
    OAuthAccountService,
)
from videocreator.infrastructure.publish.channel_publishers import (
    ChannelPublisher,
    _poll_instagram_container,
    _poll_tiktok_publish_status,
    _upload_instagram,
    _upload_tiktok,
)
from videocreator.shared.errors import ProviderError, ProviderTimeoutError, ValidationError
from videocreator.shared.ids import UserId, new_publish_account_id

USER = UserId("usr_1")


def _no_sleep(_seconds: float) -> None:
    """Injected sleep that does nothing — polling tests run instantly."""
    return None


# ============================================================================
# TikTok: upload init/PUT + status poll to completion
# ============================================================================
def test_tiktok_poll_returns_on_publish_complete() -> None:
    calls = {"n": 0}

    def poller(access_token: str, publish_id: str) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            return {"data": {"status": "PROCESSING_DOWNLOAD"}}
        return {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": "vid123"}}

    result = _poll_tiktok_publish_status(
        "at", "pub_1", status_poller=poller, sleep=_no_sleep,
    )
    assert result["status"] == "PUBLISH_COMPLETE"
    assert calls["n"] == 3


def test_tiktok_poll_raises_on_failed_status() -> None:
    def poller(access_token: str, publish_id: str) -> dict[str, Any]:
        return {"data": {"status": "FAILED", "fail_reason": "video_too_long"}}

    with pytest.raises(ProviderError, match="video_too_long"):
        _poll_tiktok_publish_status("at", "pub_1", status_poller=poller, sleep=_no_sleep)


def test_tiktok_poll_times_out_when_never_settling(monkeypatch: pytest.MonkeyPatch) -> None:
    import videocreator.infrastructure.publish.channel_publishers as mod

    # Shrink the timeout so the test doesn't need 300 fake-seconds of monotonic drift.
    monkeypatch.setattr(mod, "TIKTOK_POLL_TIMEOUT_S", 0.01)

    def poller(access_token: str, publish_id: str) -> dict[str, Any]:
        return {"data": {"status": "PROCESSING_DOWNLOAD"}}

    with pytest.raises(ProviderTimeoutError):
        _poll_tiktok_publish_status("at", "pub_1", status_poller=poller, sleep=_no_sleep)


def test_tiktok_upload_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """init -> PUT -> poll, all faked at the httpx call boundary."""

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00\x00\x00")

    class _Resp:
        def __init__(self, json_data: dict[str, Any] | None = None) -> None:
            self._json = json_data or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._json

    class _FakeHttpx:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _Resp:
            assert "publish/video/init" in url
            return _Resp({"data": {"upload_url": "https://upload.example/x", "publish_id": "pub_9"}})

        @staticmethod
        def put(url: str, **kwargs: Any) -> _Resp:
            assert url == "https://upload.example/x"
            return _Resp({})

    monkeypatch.setitem(__import__("sys").modules, "httpx", _FakeHttpx)

    def status_poller(access_token: str, publish_id: str) -> dict[str, Any]:
        assert publish_id == "pub_9"
        return {"data": {"status": "PUBLISH_COMPLETE", "share_url": "https://tiktok.com/@x/video/9"}}

    result = _upload_tiktok(
        video, {SECRET_ACCESS: "at"}, {"title": "Hola"},
        status_poller=status_poller, sleep=_no_sleep,
    )
    assert result.url == "https://tiktok.com/@x/video/9"


def test_tiktok_upload_missing_access_token_raises(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    with pytest.raises(ProviderError, match="not fully connected"):
        _upload_tiktok(video, {}, {})


# ============================================================================
# Instagram: container -> poll -> media_publish
# ============================================================================
def test_instagram_container_poll_returns_on_finished() -> None:
    calls = {"n": 0}

    def poller(access_token: str, container_id: str) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 2:
            return {"status_code": "IN_PROGRESS"}
        return {"status_code": "FINISHED"}

    _poll_instagram_container("at", "c1", container_poller=poller, sleep=_no_sleep)
    assert calls["n"] == 2


def test_instagram_container_poll_raises_on_error_status() -> None:
    def poller(access_token: str, container_id: str) -> dict[str, Any]:
        return {"status_code": "ERROR"}

    with pytest.raises(ProviderError, match="failed processing"):
        _poll_instagram_container("at", "c1", container_poller=poller, sleep=_no_sleep)


def test_instagram_upload_requires_public_video_url(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    bundle = {SECRET_ACCESS: "at", SECRET_IG_USER_ID: "ig_1"}
    with pytest.raises(ProviderError, match="public_video_url"):
        _upload_instagram(video, bundle, {})  # no metadata["public_video_url"]


def test_instagram_upload_requires_ig_user_id(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    bundle = {SECRET_ACCESS: "at"}  # no ig_user_id
    with pytest.raises(ProviderError, match="Business account id"):
        _upload_instagram(video, bundle, {"public_video_url": "https://tunnel.example/x.mp4"})


def test_instagram_upload_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    calls: list[str] = []

    class _Resp:
        def __init__(self, json_data: dict[str, Any]) -> None:
            self._json = json_data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._json

    class _FakeHttpx:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _Resp:
            calls.append(url)
            if url.endswith("/ig_1/media"):
                assert kwargs["data"]["video_url"] == "https://tunnel.example/x.mp4"
                assert kwargs["data"]["media_type"] == "REELS"
                return _Resp({"id": "container_1"})
            if url.endswith("/ig_1/media_publish"):
                assert kwargs["data"]["creation_id"] == "container_1"
                return _Resp({"id": "media_99"})
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setitem(__import__("sys").modules, "httpx", _FakeHttpx)

    def container_poller(access_token: str, container_id: str) -> dict[str, Any]:
        assert container_id == "container_1"
        return {"status_code": "FINISHED"}

    bundle = {SECRET_ACCESS: "at", SECRET_IG_USER_ID: "ig_1"}
    metadata = {"public_video_url": "https://tunnel.example/x.mp4", "title": "Hola"}
    result = _upload_instagram(
        video, bundle, metadata, container_poller=container_poller, sleep=_no_sleep,
    )
    assert result.video_id == "media_99"
    assert "media_99" in result.url
    assert calls == [
        "https://graph.facebook.com/v19.0/ig_1/media",
        "https://graph.facebook.com/v19.0/ig_1/media_publish",
    ]


def test_channel_publisher_dispatches_instagram_with_injected_pollers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end through ChannelPublisher.upload (no per-uploader override)."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")

    class _Resp:
        def __init__(self, json_data: dict[str, Any]) -> None:
            self._json = json_data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._json

    class _FakeHttpx:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _Resp:
            if url.endswith("/media"):
                return _Resp({"id": "c1"})
            return _Resp({"id": "m1"})

    monkeypatch.setitem(__import__("sys").modules, "httpx", _FakeHttpx)

    pub = ChannelPublisher(
        instagram_container_poller=lambda at, cid: {"status_code": "FINISHED"},
        sleep=_no_sleep,
    )
    result = pub.upload(
        PublishPlatform.INSTAGRAM, video,
        {SECRET_ACCESS: "at", SECRET_IG_USER_ID: "ig_1"},
        {"public_video_url": "https://tunnel.example/x.mp4"},
    )
    assert result.video_id == "m1"


# ============================================================================
# PublishService.enqueue: Instagram guard (needs PUBLIC_MEDIA_BASE_URL)
# ============================================================================
class _FakeStorage:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def open_path(self, bucket: str, key: str) -> Path:
        return self._path


class _FakeEpisodeRepo:
    def __init__(self, episode: Any) -> None:
        self._ep = episode
        self.saved: list[Any] = []

    async def get(self, episode_id):
        return self._ep

    async def save(self, ep):
        self.saved.append(ep)
        return ep


async def _sql_repos():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from videocreator.infrastructure.persistence.database import Base
    from videocreator.infrastructure.repositories.sql_repos import (
        SqlPublishAccountRepository,
        SqlPublishJobRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    return SqlPublishAccountRepository(sm), SqlPublishJobRepository(sm)


def _account(platform: PublishPlatform) -> PublishAccount:
    return PublishAccount(
        id=new_publish_account_id(), user_id=USER, platform=platform, display_name="X",
    )


def _async_const(value):
    async def _f(*_a, **_k):
        return value
    return _f


async def _make_service(tmp_path: Path, *, public_media_base_url: str | None, publisher: Any = None):
    from videocreator.application.use_cases.publishing import PublishService

    video = tmp_path / "ep.mp4"
    video.write_bytes(b"\x00")
    episode = SimpleNamespace(
        id="ep_1", final_video_key="k.mp4", dubbed_video_key=None, youtube_video_id=None,
    )
    acc_repo, job_repo = await _sql_repos()
    ep_repo = _FakeEpisodeRepo(episode)
    oauth = SimpleNamespace(credentials=_async_const({SECRET_ACCESS: "at", SECRET_IG_USER_ID: "ig_1"}))
    svc = PublishService(
        episode_repo=ep_repo, short_repo=None, storage=_FakeStorage(video),
        account_repo=acc_repo, job_repo=job_repo, oauth=oauth,
        publisher=publisher or SimpleNamespace(upload=lambda *_a, **_k: None),
        public_media_base_url=public_media_base_url,
    )
    return svc, acc_repo, ep_repo


async def test_enqueue_rejects_instagram_without_public_media_base_url(tmp_path: Path) -> None:
    svc, acc_repo, _ep = await _make_service(tmp_path, public_media_base_url=None)
    acc = _account(PublishPlatform.INSTAGRAM)
    await acc_repo.save(acc)

    with pytest.raises(ValidationError, match="PUBLIC_MEDIA_BASE_URL"):
        await svc.enqueue(
            user_id=USER, account_ids=[str(acc.id)], source="episode", source_id="ep_1",
        )


async def test_enqueue_allows_instagram_with_public_media_base_url(tmp_path: Path) -> None:
    svc, acc_repo, _ep = await _make_service(
        tmp_path, public_media_base_url="https://my-tunnel.example",
    )
    acc = _account(PublishPlatform.INSTAGRAM)
    await acc_repo.save(acc)

    jobs = await svc.enqueue(
        user_id=USER, account_ids=[str(acc.id)], source="episode", source_id="ep_1",
    )
    assert len(jobs) == 1
    assert jobs[0].status is PublishStatus.PENDING


async def test_process_builds_public_video_url_for_instagram(tmp_path: Path) -> None:
    from videocreator.infrastructure.publish.youtube_publisher import UploadResult

    seen: dict[str, Any] = {}

    class _CapturingPublisher:
        def upload(self, platform, path, bundle, metadata):
            seen["metadata"] = metadata
            return UploadResult(video_id="m1", url="https://instagram.com/reel/m1/")

    svc, acc_repo, _ep = await _make_service(
        tmp_path, public_media_base_url="https://my-tunnel.example",
        publisher=_CapturingPublisher(),
    )
    acc = _account(PublishPlatform.INSTAGRAM)
    await acc_repo.save(acc)
    [job] = await svc.enqueue(
        user_id=USER, account_ids=[str(acc.id)], source="episode", source_id="ep_1",
    )

    done = await svc.process(job)

    assert done.status is PublishStatus.PUBLISHED
    assert seen["metadata"]["public_video_url"] == (
        "https://my-tunnel.example/api/v1/storage/episodes/k.mp4"
    )


# ============================================================================
# OAuthAccountService.verify — account health check
# ============================================================================
class _FakeVault:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    async def get_secret(self, user_id: UserId, provider: str) -> str | None:
        return self.store.get((str(user_id), provider))

    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None:
        self.store[(str(user_id), provider)] = value

    async def delete_secret(self, user_id: UserId, provider: str) -> None:
        self.store.pop((str(user_id), provider), None)

    async def list_providers(self, user_id: UserId) -> list[str]:
        return sorted(p for (u, p) in self.store if u == str(user_id))


class _FakeAccountRepo:
    def __init__(self) -> None:
        self.accounts: dict[str, PublishAccount] = {}

    async def get(self, account_id):
        return self.accounts.get(str(account_id))

    async def list_for_user(self, user_id):
        return [a for a in self.accounts.values() if a.user_id == user_id]

    async def save(self, account):
        self.accounts[str(account.id)] = account
        return account

    async def delete(self, account_id):
        self.accounts.pop(str(account_id), None)


async def test_verify_marks_account_expired_when_probe_fails() -> None:
    vault, repo = _FakeVault(), _FakeAccountRepo()
    svc = OAuthAccountService(
        vault, repo,
        auth_code_flow=lambda *_a: {"access_token": "at-0"},
        verify_probe=lambda platform, bundle: False,
    )
    acc = await svc.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")

    result = await svc.verify(acc)

    assert result.status is AccountStatus.EXPIRED
    assert repo.accounts[str(acc.id)].status is AccountStatus.EXPIRED


async def test_verify_keeps_account_connected_when_probe_succeeds() -> None:
    vault, repo = _FakeVault(), _FakeAccountRepo()
    svc = OAuthAccountService(
        vault, repo,
        auth_code_flow=lambda *_a: {"access_token": "at-0"},
        verify_probe=lambda platform, bundle: True,
    )
    acc = await svc.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")

    result = await svc.verify(acc)

    assert result.status is AccountStatus.CONNECTED


async def test_verify_restores_connected_status_when_probe_recovers() -> None:
    vault, repo = _FakeVault(), _FakeAccountRepo()
    svc = OAuthAccountService(
        vault, repo,
        auth_code_flow=lambda *_a: {"access_token": "at-0"},
        verify_probe=lambda platform, bundle: True,
    )
    acc = await svc.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")
    expired = acc.model_copy(update={"status": AccountStatus.EXPIRED})
    await repo.save(expired)

    result = await svc.verify(expired)

    assert result.status is AccountStatus.CONNECTED


async def test_verify_propagates_refresh_failure_as_expired() -> None:
    """A dead refresh token surfaces through credentials() before the probe
    ever runs — verify() must still report EXPIRED, not raise."""
    def boom(refresh_token, client_id, client_secret):
        raise RuntimeError("401 unauthorized")

    vault, repo = _FakeVault(), _FakeAccountRepo()
    svc = OAuthAccountService(
        vault, repo,
        auth_code_flow=lambda *_a: {"access_token": "at-0", "refresh_token": "rt-tt"},
        tiktok_refresh_flow=boom,
    )
    acc = await svc.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")

    result = await svc.verify(acc)

    assert result.status is AccountStatus.EXPIRED


# ============================================================================
# Router: POST /channels/{account_id}/verify
# ============================================================================
class _FakeRuntimeConfig:
    def get(self) -> dict[str, Any]:
        return {"channels_feature_enabled": True}


class _FakeContainer:
    def __init__(self, oauth: OAuthAccountService, repo: _FakeAccountRepo) -> None:
        self._oauth = oauth
        self._repo = repo

    def runtime_config(self) -> _FakeRuntimeConfig:
        return _FakeRuntimeConfig()

    def oauth_account_service(self) -> OAuthAccountService:
        return self._oauth

    def publish_account_repo(self) -> _FakeAccountRepo:
        return self._repo


async def test_verify_router_marks_expired_and_returns_dto() -> None:
    from videocreator.interfaces.rest.routers import channels as channels_router

    vault, repo = _FakeVault(), _FakeAccountRepo()
    oauth = OAuthAccountService(
        vault, repo,
        auth_code_flow=lambda *_a: {"access_token": "at-0"},
        verify_probe=lambda platform, bundle: False,
    )
    acc = await oauth.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")
    container = _FakeContainer(oauth, repo)

    resp = await channels_router.verify_account(str(acc.id), container, USER)

    assert resp.status == "expired"
    assert resp.platform == "tiktok"


async def test_verify_router_404_for_other_users_account() -> None:
    from fastapi import HTTPException

    from videocreator.interfaces.rest.routers import channels as channels_router

    vault, repo = _FakeVault(), _FakeAccountRepo()
    oauth = OAuthAccountService(vault, repo, auth_code_flow=lambda *_a: {"access_token": "at-0"})
    acc = await oauth.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")
    container = _FakeContainer(oauth, repo)

    with pytest.raises(HTTPException) as exc_info:
        await channels_router.verify_account(str(acc.id), container, UserId("usr_other"))
    assert exc_info.value.status_code == 404
