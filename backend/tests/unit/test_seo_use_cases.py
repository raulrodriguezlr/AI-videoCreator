"""Tests for the SEO metadata + title-bandit use cases.

The LLM and repositories are faked; the real `LinUcbBandit` runs so the
learning loop (generate -> recommend -> feedback -> recommend) is exercised
end to end without any I/O.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.seo import (
    GenerateSeoMetadata,
    GetSeoMetadata,
    RecommendTitle,
    RecordTitleOutcome,
)
from videocreator.domain.entities import Episode, Pod, PodConfig, SeoMetadata
from videocreator.domain.services.linucb import LinUcbBandit
from videocreator.domain.value_objects import StyleProfile
from videocreator.shared.errors import (
    EpisodeNotFound,
    ForbiddenError,
    ProviderError,
    SeoMetadataNotFound,
    ValidationError,
)
from videocreator.shared.ids import EpisodeId, PodId, UserId

OWNER = UserId("usr_1")
OTHER = UserId("usr_2")


# ============================================================================
# Fakes
# ============================================================================
class _FakePodRepo:
    def __init__(self, pod: Pod) -> None:
        self._pod = pod

    async def get(self, pid: PodId) -> Pod | None:
        return self._pod if pid == self._pod.id else None

    async def list_for_user(self, uid: UserId) -> list[Pod]:
        return [self._pod]

    async def save(self, p: Pod) -> Pod:
        return p

    async def delete(self, pid: PodId) -> None: ...


class _FakeEpisodeRepo:
    def __init__(self, episode: Episode | None) -> None:
        self._episode = episode

    async def get(self, eid: EpisodeId) -> Episode | None:
        return self._episode

    async def save(self, ep: Episode) -> Episode:
        return ep

    async def list_for_pod(self, pod_id: PodId) -> list[Episode]:
        return [self._episode] if self._episode else []

    async def next_number(self, pod_id: PodId) -> int:
        return 1


class _FakeSeoRepo:
    def __init__(self) -> None:
        self._by_episode: dict[str, SeoMetadata] = {}
        self.saves = 0

    async def get(self, seo_id: Any) -> SeoMetadata | None:
        for seo in self._by_episode.values():
            if seo.id == seo_id:
                return seo.model_copy(deep=True)
        return None

    async def get_for_episode(self, episode_id: EpisodeId) -> SeoMetadata | None:
        seo = self._by_episode.get(episode_id)
        return seo.model_copy(deep=True) if seo else None

    async def list_for_pod(self, pod_id: PodId) -> list[SeoMetadata]:
        return [s.model_copy(deep=True) for s in self._by_episode.values()]

    async def save(self, metadata: SeoMetadata) -> SeoMetadata:
        self.saves += 1
        self._by_episode[metadata.episode_id] = metadata.model_copy(deep=True)
        return metadata


class _FakeLLM:
    """Returns a canned JSON payload; records the prompts it receives."""

    def __init__(self, payload: dict[str, Any] | str) -> None:
        self._raw = payload if isinstance(payload, str) else json.dumps(payload)
        self.prompts: list[str] = []

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        self.prompts.append(prompt)
        return self._raw


# ============================================================================
# Builders
# ============================================================================
def _pod() -> Pod:
    return Pod(
        id=PodId("pod_1"),
        owner_id=OWNER,
        name="cosmos",
        config=PodConfig(
            series_name="Curiosos del Cosmos",
            style_profile=StyleProfile.CINEMATIC_3D,
            art_style="3D",
        ),
    )


def _episode() -> Episode:
    return Episode(
        id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), title="Black Holes 101", number=1,
    )


def _payload(titles: list[str] | None = None) -> dict[str, Any]:
    return {
        "description": "A whirlwind tour of black holes.",
        "tags": ["space", "physics", "space"],  # dup → deduped
        "hashtags": ["#space", "#science"],
        "titles": titles if titles is not None else [
            "Black Holes Explained", "The Truth About Black Holes", "Inside a Black Hole",
        ],
    }


def _generate_uc(
    *, llm: _FakeLLM, seo_repo: _FakeSeoRepo, episode: Episode | None, bandit: LinUcbBandit,
) -> GenerateSeoMetadata:
    return GenerateSeoMetadata(
        pod_repo=_FakePodRepo(_pod()),  # type: ignore[arg-type]
        episode_repo=_FakeEpisodeRepo(episode),  # type: ignore[arg-type]
        seo_repo=seo_repo,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        bandit=bandit,
    )


# ============================================================================
# GenerateSeoMetadata
# ============================================================================
async def test_generate_creates_metadata_and_seeds_bandit() -> None:
    # Arrange
    repo = _FakeSeoRepo()
    uc = _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=repo, episode=_episode(), bandit=LinUcbBandit(),
    )

    # Act
    seo = await uc.execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)

    # Assert — metadata fields parsed; tags deduped; bandit seeded over titles
    assert seo.description == "A whirlwind tour of black holes."
    assert seo.tags == ["space", "physics"]
    assert seo.hashtags == ["#space", "#science"]
    assert len(seo.title_variants) == 3
    assert seo.policy is not None
    assert seo.policy.arm_ids == tuple(seo.title_variants)
    assert seo.selected_title == seo.title_variants[0]


async def test_generate_caps_variants_to_requested_count() -> None:
    # Arrange — LLM offers 3 titles but caller wants only 2
    uc = _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=_FakeSeoRepo(), episode=_episode(),
        bandit=LinUcbBandit(),
    )

    # Act
    seo = await uc.execute(
        pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER,
        variant_count=2,
    )

    # Assert
    assert len(seo.title_variants) == 2


async def test_generate_falls_back_to_episode_title_without_titles() -> None:
    # Arrange — LLM returns no usable titles
    uc = _generate_uc(
        llm=_FakeLLM(_payload(titles=[])), seo_repo=_FakeSeoRepo(), episode=_episode(),
        bandit=LinUcbBandit(),
    )

    # Act
    seo = await uc.execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)

    # Assert
    assert seo.title_variants == ["Black Holes 101"]


async def test_generate_rejects_non_owner() -> None:
    uc = _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=_FakeSeoRepo(), episode=_episode(),
        bandit=LinUcbBandit(),
    )
    with pytest.raises(ForbiddenError):
        await uc.execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OTHER)


async def test_generate_rejects_episode_outside_pod() -> None:
    uc = _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=_FakeSeoRepo(), episode=None, bandit=LinUcbBandit(),
    )
    with pytest.raises(EpisodeNotFound):
        await uc.execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)


async def test_generate_raises_on_invalid_json() -> None:
    uc = _generate_uc(
        llm=_FakeLLM("not-json"), seo_repo=_FakeSeoRepo(), episode=_episode(),
        bandit=LinUcbBandit(),
    )
    with pytest.raises(ProviderError, match="invalid JSON"):
        await uc.execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)


async def test_generate_is_idempotent_per_episode() -> None:
    # Arrange — generate twice for the same episode
    repo = _FakeSeoRepo()
    uc = _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=repo, episode=_episode(), bandit=LinUcbBandit(),
    )

    # Act
    eid = EpisodeId("ep_1")
    first = await uc.execute(pod_id=PodId("pod_1"), episode_id=eid, requester_id=OWNER)
    second = await uc.execute(pod_id=PodId("pod_1"), episode_id=eid, requester_id=OWNER)

    # Assert — same identity reused, created_at preserved (no orphaned rows)
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert len(repo._by_episode) == 1


# ============================================================================
# Get / Recommend / RecordOutcome
# ============================================================================
async def test_get_raises_when_missing() -> None:
    uc = GetSeoMetadata(_FakePodRepo(_pod()), _FakeSeoRepo())  # type: ignore[arg-type]
    with pytest.raises(SeoMetadataNotFound):
        await uc.execute(episode_id=EpisodeId("ep_1"), requester_id=OWNER)


async def test_recommend_picks_variant_and_persists_selection() -> None:
    # Arrange — seed metadata first
    repo = _FakeSeoRepo()
    bandit = LinUcbBandit()
    await _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=repo, episode=_episode(), bandit=bandit,
    ).execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)
    uc = RecommendTitle(_FakePodRepo(_pod()), repo, bandit)  # type: ignore[arg-type]

    # Act
    decision = await uc.execute(episode_id=EpisodeId("ep_1"), requester_id=OWNER)

    # Assert — a real variant chosen; scores cover all arms; selection persisted
    stored = await repo.get_for_episode(EpisodeId("ep_1"))
    assert decision.arm_id in stored.title_variants  # type: ignore[union-attr]
    assert set(decision.scores) == set(stored.title_variants)  # type: ignore[union-attr]
    assert stored.selected_title == decision.arm_id  # type: ignore[union-attr]


async def test_feedback_shifts_recommendation_to_rewarded_title() -> None:
    # Arrange — contextless exploitation (alpha=0) so rewards dominate cleanly
    repo = _FakeSeoRepo()
    bandit = LinUcbBandit(alpha=0.0)
    titles = ["Title A", "Title B"]
    await _generate_uc(
        llm=_FakeLLM(_payload(titles=titles)), seo_repo=repo, episode=_episode(), bandit=bandit,
    ).execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)
    feedback = RecordTitleOutcome(_FakePodRepo(_pod()), repo, bandit)  # type: ignore[arg-type]
    recommend = RecommendTitle(_FakePodRepo(_pod()), repo, bandit)  # type: ignore[arg-type]

    # Act — reward "Title B" repeatedly, then ask for the best
    for _ in range(5):
        await feedback.execute(
            episode_id=EpisodeId("ep_1"), requester_id=OWNER, title="Title B", reward=1.0,
        )
    decision = await recommend.execute(episode_id=EpisodeId("ep_1"), requester_id=OWNER)

    # Assert
    assert decision.arm_id == "Title B"
    assert decision.scores["Title B"] > decision.scores["Title A"]


async def test_feedback_unknown_title_raises() -> None:
    repo = _FakeSeoRepo()
    bandit = LinUcbBandit()
    await _generate_uc(
        llm=_FakeLLM(_payload()), seo_repo=repo, episode=_episode(), bandit=bandit,
    ).execute(pod_id=PodId("pod_1"), episode_id=EpisodeId("ep_1"), requester_id=OWNER)
    uc = RecordTitleOutcome(_FakePodRepo(_pod()), repo, bandit)  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="unknown title variant"):
        await uc.execute(
            episode_id=EpisodeId("ep_1"), requester_id=OWNER, title="ghost", reward=1.0,
        )
