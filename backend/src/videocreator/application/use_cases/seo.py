"""SEO metadata + title-optimization use cases (Plan Maestro §B SEO + bandits).

`GenerateSeoMetadata` asks the LLM for a description, tags, hashtags and several
candidate titles for an episode, then cold-starts a LinUCB policy over those
titles. `RecommendTitle` / `RecordTitleOutcome` close the learning loop: pick
the current best title and feed observed engagement back into the policy.

The bandit is run *contextless* for now (a single bias feature) — the policy
and `LinUcbBandit` already support richer feature vectors, so real signals
(audience, time-of-day, platform) can be layered in without touching callers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Episode, Pod, SeoMetadata
from videocreator.domain.ports import (
    EpisodeRepository,
    LLMPort,
    PodRepository,
    SeoRepository,
)
from videocreator.domain.services.linucb import LinUcbBandit
from videocreator.domain.value_objects import BanditDecision
from videocreator.shared.errors import (
    EpisodeNotFound,
    ForbiddenError,
    PodNotFound,
    ProviderError,
    SeoMetadataNotFound,
    ValidationError,
)
from videocreator.shared.ids import EpisodeId, PodId, SeoId, UserId, new_seo_id
from videocreator.shared.time import utcnow

# Contextless bandit: one constant bias feature. Swap for a real feature vector
# (and a wider `dimension`) once engagement signals are available.
_CONTEXT_DIM = 1
_TITLE_CONTEXT: tuple[float, ...] = (1.0,)

_SEO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "titles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["description", "titles"],
}


async def _owned_pod(pod_repo: PodRepository, pod_id: PodId, requester_id: UserId) -> Pod:
    pod = await pod_repo.get(pod_id)
    if pod is None:
        raise PodNotFound(f"pod {pod_id} not found")
    if not pod.is_owned_by(requester_id):
        raise ForbiddenError("pod is owned by a different user")
    return pod


def _render_seo_prompt(*, pod: Pod, episode: Episode, variant_count: int) -> str:
    return (
        f"You are a YouTube/TikTok growth strategist for the series "
        f"'{pod.config.series_name}'. Audience: {pod.config.target_audience}. "
        f"Language: {pod.config.language}.\n\n"
        f"Episode title: {episode.title}\n\n"
        f"Produce publishing SEO metadata:\n"
        f"- a compelling description (2-3 sentences, keyword-rich, no clickbait),\n"
        f"- 8-12 lowercase search tags (no '#'),\n"
        f"- 3-6 hashtags (with '#'),\n"
        f"- exactly {variant_count} distinct, high-CTR title variants to A/B test.\n"
        f"Return strict JSON matching the supplied schema."
    )


def _clean_titles(raw: object, *, fallback: str, limit: int) -> list[str]:
    """Dedupe, strip and cap LLM titles; fall back to the episode title."""
    titles: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item).strip()
            if text and text not in titles:
                titles.append(text)
            if len(titles) >= limit:
                break
    return titles or [fallback]


def _clean_strings(raw: object, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


@dataclass(frozen=True, slots=True)
class GenerateSeoMetadata:
    pod_repo: PodRepository
    episode_repo: EpisodeRepository
    seo_repo: SeoRepository
    llm: LLMPort
    bandit: LinUcbBandit

    async def execute(
        self,
        *,
        pod_id: PodId,
        episode_id: EpisodeId,
        requester_id: UserId,
        variant_count: int = 4,
    ) -> SeoMetadata:
        pod = await _owned_pod(self.pod_repo, pod_id, requester_id)
        episode = await self.episode_repo.get(episode_id)
        if episode is None or episode.pod_id != pod_id:
            raise EpisodeNotFound(f"episode {episode_id} not found in pod {pod_id}")

        prompt = _render_seo_prompt(pod=pod, episode=episode, variant_count=variant_count)
        raw = await self.llm.complete(prompt, response_schema=_SEO_SCHEMA, temperature=0.9)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"LLM returned invalid JSON: {exc}") from exc

        titles = _clean_titles(
            data.get("titles"), fallback=episode.title, limit=variant_count
        )
        policy = self.bandit.cold_start(titles, dimension=_CONTEXT_DIM)

        existing = await self.seo_repo.get_for_episode(episode_id)
        seo_id: SeoId = existing.id if existing else new_seo_id()
        metadata = SeoMetadata(
            id=seo_id,
            pod_id=pod_id,
            episode_id=episode_id,
            description=str(data.get("description") or "").strip(),
            tags=_clean_strings(data.get("tags"), limit=15),
            hashtags=_clean_strings(data.get("hashtags"), limit=10),
            title_variants=titles,
            policy=policy,
            selected_title=titles[0],
            created_at=existing.created_at if existing else utcnow(),
            updated_at=utcnow(),
        )
        return await self.seo_repo.save(metadata)


@dataclass(frozen=True, slots=True)
class GetSeoMetadata:
    pod_repo: PodRepository
    seo_repo: SeoRepository

    async def execute(self, *, episode_id: EpisodeId, requester_id: UserId) -> SeoMetadata:
        seo = await self.seo_repo.get_for_episode(episode_id)
        if seo is None:
            raise SeoMetadataNotFound(f"no SEO metadata for episode {episode_id}")
        await _owned_pod(self.pod_repo, seo.pod_id, requester_id)
        return seo


@dataclass(frozen=True, slots=True)
class RecommendTitle:
    pod_repo: PodRepository
    seo_repo: SeoRepository
    bandit: LinUcbBandit

    async def execute(
        self, *, episode_id: EpisodeId, requester_id: UserId
    ) -> BanditDecision:
        seo = await self.seo_repo.get_for_episode(episode_id)
        if seo is None:
            raise SeoMetadataNotFound(f"no SEO metadata for episode {episode_id}")
        await _owned_pod(self.pod_repo, seo.pod_id, requester_id)
        if seo.policy is None or not seo.title_variants:
            raise ValidationError("SEO metadata has no title variants to recommend")

        decision = self.bandit.recommend(seo.policy, _TITLE_CONTEXT)
        seo.selected_title = decision.arm_id
        seo.updated_at = utcnow()
        await self.seo_repo.save(seo)
        return decision


@dataclass(frozen=True, slots=True)
class RecordTitleOutcome:
    pod_repo: PodRepository
    seo_repo: SeoRepository
    bandit: LinUcbBandit

    async def execute(
        self,
        *,
        episode_id: EpisodeId,
        requester_id: UserId,
        title: str,
        reward: float,
    ) -> SeoMetadata:
        seo = await self.seo_repo.get_for_episode(episode_id)
        if seo is None:
            raise SeoMetadataNotFound(f"no SEO metadata for episode {episode_id}")
        await _owned_pod(self.pod_repo, seo.pod_id, requester_id)
        if seo.policy is None:
            raise ValidationError("SEO metadata has no bandit policy to update")
        try:
            updated = self.bandit.update(
                seo.policy, arm_id=title, context=_TITLE_CONTEXT, reward=reward
            )
        except KeyError as exc:
            raise ValidationError(f"unknown title variant: {title!r}") from exc

        seo.policy = updated
        seo.updated_at = utcnow()
        return await self.seo_repo.save(seo)


__all__ = [
    "GenerateSeoMetadata",
    "GetSeoMetadata",
    "RecommendTitle",
    "RecordTitleOutcome",
]
