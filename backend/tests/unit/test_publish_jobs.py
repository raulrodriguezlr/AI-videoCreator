"""Channels Hub service tests: OAuth account connect/disconnect + upload dispatch.

Flows and platform uploaders are injected with fakes so nothing touches the
network or a browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.domain.entities import PublishAccount
from videocreator.domain.value_objects import AccountStatus, PublishPlatform
from videocreator.infrastructure.publish.channel_accounts import (
    OAuthAccountService,
    SECRET_REFRESH,
    _key,
)
from videocreator.infrastructure.publish.channel_publishers import (
    ChannelPublisher,
    UploadResult,
)
from videocreator.shared.ids import UserId, new_publish_account_id

USER = UserId("usr_1")


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


def _service(**kw) -> tuple[OAuthAccountService, _FakeVault, _FakeAccountRepo]:
    vault, repo = _FakeVault(), _FakeAccountRepo()
    return OAuthAccountService(vault, repo, **kw), vault, repo  # type: ignore[arg-type]


# ============================================================================
# OAuth connect / disconnect
# ============================================================================
async def test_connect_youtube_creates_account_and_stores_tokens() -> None:
    svc, vault, repo = _service(youtube_flow=lambda cid, cs: {"refresh_token": "rt-xyz"})

    acc = await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="cid", client_secret="cs")

    assert acc.platform is PublishPlatform.YOUTUBE
    assert acc.status is AccountStatus.CONNECTED
    assert str(acc.id) in repo.accounts
    # token stored scoped per-account
    assert vault.store[(str(USER), _key(PublishPlatform.YOUTUBE, str(acc.id), SECRET_REFRESH))] == "rt-xyz"


async def test_connect_supports_multiple_youtube_accounts() -> None:
    svc, _vault, repo = _service(youtube_flow=lambda cid, cs: {"refresh_token": "rt"})

    a1 = await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="c", client_secret="s")
    a2 = await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="c", client_secret="s")

    assert a1.id != a2.id
    assert len(await svc.list_accounts(USER)) == 2


async def test_connect_tiktok_uses_auth_code_flow() -> None:
    captured = {}

    def fake_auth_code(platform, cid, cs, cfg):
        captured["platform"] = platform
        return {"access_token": "at-1", "display_name": "Piña TikTok", "handle": "@pina"}

    svc, vault, _repo = _service(auth_code_flow=fake_auth_code)
    acc = await svc.connect(USER, PublishPlatform.TIKTOK, client_id="k", client_secret="s")

    assert captured["platform"] is PublishPlatform.TIKTOK
    assert acc.display_name == "Piña TikTok"


async def test_connect_requires_client_credentials() -> None:
    svc, _v, _r = _service()
    with pytest.raises(ValueError):
        await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="", client_secret="")


async def test_disconnect_removes_account_and_secrets() -> None:
    svc, vault, repo = _service(youtube_flow=lambda cid, cs: {"refresh_token": "rt"})
    acc = await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="c", client_secret="s")

    await svc.disconnect(acc)

    assert str(acc.id) not in repo.accounts
    assert vault.list_providers and await vault.list_providers(USER) == []


async def test_credentials_returns_stored_bundle() -> None:
    svc, _v, _r = _service(youtube_flow=lambda cid, cs: {"refresh_token": "rt"})
    acc = await svc.connect(USER, PublishPlatform.YOUTUBE, client_id="cid", client_secret="csec")

    bundle = await svc.credentials(acc)
    assert bundle[SECRET_REFRESH] == "rt"
    assert bundle["client_id"] == "cid"


# ============================================================================
# Upload dispatch
# ============================================================================
async def test_channel_publisher_dispatches_to_platform(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00\x00")
    seen = {}

    def fake_yt(path, bundle, meta):
        seen["title"] = meta["title"]
        return UploadResult(video_id="vid1", url="https://youtu.be/vid1")

    pub = ChannelPublisher(uploaders={PublishPlatform.YOUTUBE: fake_yt})
    result = pub.upload(PublishPlatform.YOUTUBE, video, {"refresh_token": "rt"}, {"title": "Hola"})

    assert result.video_id == "vid1"
    assert seen["title"] == "Hola"


def test_channel_publisher_missing_file_raises(tmp_path: Path) -> None:
    pub = ChannelPublisher(uploaders={})
    with pytest.raises(FileNotFoundError):
        pub.upload(PublishPlatform.YOUTUBE, tmp_path / "nope.mp4", {}, {})


# ============================================================================
# PublishService: enqueue (batch) + process (status transitions)
# ============================================================================
from types import SimpleNamespace  # noqa: E402

from videocreator.application.use_cases.publishing import PublishService  # noqa: E402
from videocreator.domain.value_objects import PublishStatus  # noqa: E402
from videocreator.shared.errors import ValidationError  # noqa: E402


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


class _OkPublisher:
    def upload(self, platform, path, bundle, metadata):
        return UploadResult(video_id="vid9", url="https://youtu.be/vid9")


class _BoomPublisher:
    def upload(self, platform, path, bundle, metadata):
        raise RuntimeError("api exploded")


async def _service_with(tmp_path: Path, *, publisher) -> tuple[PublishService, Any, Any]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from videocreator.infrastructure.persistence.database import Base
    from videocreator.infrastructure.repositories.sql_repos import (
        SqlPublishAccountRepository,
        SqlPublishJobRepository,
    )

    video = tmp_path / "ep.mp4"
    video.write_bytes(b"\x00")
    episode = SimpleNamespace(
        id="ep_1", final_video_key="k.mp4", dubbed_video_key=None, youtube_video_id=None,
    )
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    acc_repo = SqlPublishAccountRepository(sm)
    job_repo = SqlPublishJobRepository(sm)
    ep_repo = _FakeEpisodeRepo(episode)
    oauth = SimpleNamespace(credentials=_async_const({"refresh_token": "rt"}))
    svc = PublishService(
        episode_repo=ep_repo, short_repo=None, storage=_FakeStorage(video),
        account_repo=acc_repo, job_repo=job_repo, oauth=oauth, publisher=publisher,
    )
    return svc, acc_repo, ep_repo


def _async_const(value):
    async def _f(*_a, **_k):
        return value
    return _f


async def test_enqueue_creates_job_per_account(tmp_path: Path) -> None:
    svc, acc_repo, _ep = await _service_with(tmp_path, publisher=_OkPublisher())
    a1 = _account_for(acc_repo)
    a2 = _account_for(acc_repo)
    await acc_repo.save(a1)
    await acc_repo.save(a2)

    jobs = await svc.enqueue(
        user_id=USER, account_ids=[str(a1.id), str(a2.id)],
        source="episode", source_id="ep_1", metadata={"title": "X"},
    )
    assert len(jobs) == 2
    assert all(j.status is PublishStatus.PENDING for j in jobs)


async def test_enqueue_rejects_unknown_source(tmp_path: Path) -> None:
    svc, _a, _e = await _service_with(tmp_path, publisher=_OkPublisher())
    with pytest.raises(ValidationError):
        await svc.enqueue(user_id=USER, account_ids=["x"], source="bogus", source_id="ep_1")


async def test_process_marks_published_and_stamps_episode(tmp_path: Path) -> None:
    svc, acc_repo, ep_repo = await _service_with(tmp_path, publisher=_OkPublisher())
    acc = _account_for(acc_repo)
    await acc_repo.save(acc)
    [job] = await svc.enqueue(
        user_id=USER, account_ids=[str(acc.id)], source="episode", source_id="ep_1",
    )

    done = await svc.process(job)

    assert done.status is PublishStatus.PUBLISHED
    assert done.result_url == "https://youtu.be/vid9"
    assert ep_repo.saved and ep_repo.saved[-1].youtube_video_id == "vid9"


async def test_process_records_error_on_failure(tmp_path: Path) -> None:
    svc, acc_repo, _ep = await _service_with(tmp_path, publisher=_BoomPublisher())
    acc = _account_for(acc_repo)
    await acc_repo.save(acc)
    [job] = await svc.enqueue(
        user_id=USER, account_ids=[str(acc.id)], source="episode", source_id="ep_1",
    )

    done = await svc.process(job)

    assert done.status is PublishStatus.ERROR
    assert "exploded" in (done.error or "")


def _account_for(_repo) -> PublishAccount:
    return PublishAccount(
        id=new_publish_account_id(), user_id=USER, platform=PublishPlatform.YOUTUBE,
        display_name="YT",
    )
