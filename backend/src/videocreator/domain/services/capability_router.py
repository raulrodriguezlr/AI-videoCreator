"""Capability-based provider routing with scoring, circuit breaker, and cost awareness.

Pure domain service — no I/O, fully testable. Takes provider metadata and health
snapshots as inputs, returns ordered fallback chains as output.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class RouteWeights:
    """Slider weights for quality/cost/speed tradeoff. Must sum to 1."""

    quality: float = 0.5
    cost: float = 0.25
    speed: float = 0.25


@dataclass(frozen=True)
class CapabilityRequest:
    """What the caller needs from a provider."""

    capability: str
    duration_s: float = 5.0
    max_cost_usd: float | None = None
    weights: RouteWeights = field(default_factory=RouteWeights)


@dataclass
class HealthSnapshot:
    """In-memory circuit breaker state for one provider."""

    provider_id: str
    failures: int = 0
    window_start: float = 0.0
    open_until: float = 0.0

    _WINDOW_S: float = 300.0  # 5 min
    _THRESHOLD: int = 5
    _COOLDOWN_S: float = 600.0  # 10 min

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self.open_until

    def record_failure(self) -> None:
        now = time.monotonic()
        if now - self.window_start > self._WINDOW_S:
            self.failures = 0
            self.window_start = now
        self.failures += 1
        if self.failures >= self._THRESHOLD:
            self.open_until = now + self._COOLDOWN_S
            log.warning(
                "circuit_breaker.open",
                provider=self.provider_id,
                cooldown_s=self._COOLDOWN_S,
            )

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0


@dataclass(frozen=True)
class ProviderInfo:
    """Minimal provider metadata needed for routing decisions."""

    id: str
    capabilities: list[str]
    quality_score: float = 0.5
    latency_p50_s: float = 30.0
    cost_per_second_usd: float = 0.0
    cost_per_request_usd: float = 0.0
    tags: list[str] = field(default_factory=list)

    def estimate_cost(self, duration_s: float) -> float:
        return self.cost_per_request_usd + self.cost_per_second_usd * duration_s


@dataclass
class CostEntry:
    """A single cost ledger entry."""

    provider_id: str
    capability: str
    units: float
    unit_type: str
    cost_usd: float
    timestamp: float = field(default_factory=time.time)
    episode_id: str | None = None


class HealthTracker:
    """Tracks circuit breaker state for all providers."""

    def __init__(self) -> None:
        self._snapshots: dict[str, HealthSnapshot] = {}

    def get(self, provider_id: str) -> HealthSnapshot:
        if provider_id not in self._snapshots:
            self._snapshots[provider_id] = HealthSnapshot(provider_id=provider_id)
        return self._snapshots[provider_id]

    def record_failure(self, provider_id: str) -> None:
        self.get(provider_id).record_failure()

    def record_success(self, provider_id: str) -> None:
        self.get(provider_id).record_success()


class CostLedger:
    """In-memory cost tracking with budget enforcement."""

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []

    def record(self, entry: CostEntry) -> None:
        self._entries.append(entry)

    def total_cost(self, *, episode_id: str | None = None) -> float:
        entries = self._entries
        if episode_id is not None:
            entries = [e for e in entries if e.episode_id == episode_id]
        return sum(e.cost_usd for e in entries)

    def check_budget(self, estimated_cost: float, budget_usd: float | None) -> bool:
        """Returns True if adding estimated_cost stays within budget."""
        if budget_usd is None:
            return True
        return self.total_cost() + estimated_cost <= budget_usd

    @property
    def entries(self) -> list[CostEntry]:
        return list(self._entries)


def score_provider(
    provider: ProviderInfo,
    request: CapabilityRequest,
    health: HealthSnapshot,
) -> float:
    """Score a provider for a given request. Returns -1 if ineligible."""
    if request.capability not in provider.capabilities:
        return -1.0
    if health.circuit_open:
        return -1.0
    estimated = provider.estimate_cost(request.duration_s)
    if request.max_cost_usd is not None and estimated > request.max_cost_usd:
        return -1.0

    q = provider.quality_score
    speed = 1.0 / max(provider.latency_p50_s, 1.0)
    cost_inv = 1.0 / max(estimated, 0.001)

    w = request.weights
    return w.quality * q + w.cost * cost_inv * 0.1 + w.speed * speed * 10.0


def route(
    providers: list[ProviderInfo],
    request: CapabilityRequest,
    health_tracker: HealthTracker,
) -> list[ProviderInfo]:
    """Return providers ordered by score descending. Ineligible providers excluded."""
    scored = []
    for p in providers:
        s = score_provider(p, request, health_tracker.get(p.id))
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


__all__ = [
    "CapabilityRequest",
    "CostEntry",
    "CostLedger",
    "HealthSnapshot",
    "HealthTracker",
    "ProviderInfo",
    "RouteWeights",
    "route",
    "score_provider",
]
