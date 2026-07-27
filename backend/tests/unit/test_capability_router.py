"""Tests for capability router — scoring, circuit breaker, cost ledger."""
from __future__ import annotations

import time

import pytest

from videocreator.domain.services.capability_router import (
    CapabilityRequest,
    CostEntry,
    CostLedger,
    HealthSnapshot,
    HealthTracker,
    ProviderInfo,
    RouteWeights,
    route,
    score_provider,
)


def _provider(
    id: str = "p1",
    capabilities: list[str] | None = None,
    quality: float = 0.7,
    latency: float = 30.0,
    cost_s: float = 0.05,
    cost_req: float = 0.10,
) -> ProviderInfo:
    return ProviderInfo(
        id=id,
        capabilities=capabilities or ["text_to_video"],
        quality_score=quality,
        latency_p50_s=latency,
        cost_per_second_usd=cost_s,
        cost_per_request_usd=cost_req,
    )


class TestScoring:
    def test_eligible_provider_gets_positive_score(self) -> None:
        p = _provider()
        req = CapabilityRequest(capability="text_to_video")
        health = HealthSnapshot(provider_id="p1")
        s = score_provider(p, req, health)
        assert s > 0

    def test_wrong_capability_returns_negative(self) -> None:
        p = _provider(capabilities=["image_to_video"])
        req = CapabilityRequest(capability="text_to_video")
        health = HealthSnapshot(provider_id="p1")
        assert score_provider(p, req, health) == -1.0

    def test_open_circuit_returns_negative(self) -> None:
        p = _provider()
        req = CapabilityRequest(capability="text_to_video")
        health = HealthSnapshot(provider_id="p1", open_until=time.monotonic() + 600)
        assert score_provider(p, req, health) == -1.0

    def test_over_budget_returns_negative(self) -> None:
        p = _provider(cost_s=1.0, cost_req=0.0)
        req = CapabilityRequest(capability="text_to_video", duration_s=10, max_cost_usd=5.0)
        health = HealthSnapshot(provider_id="p1")
        assert score_provider(p, req, health) == -1.0

    def test_quality_weighted_higher(self) -> None:
        p_hi = _provider(id="hi", quality=0.9, latency=60, cost_s=0.10)
        p_lo = _provider(id="lo", quality=0.3, latency=10, cost_s=0.01)
        req = CapabilityRequest(
            capability="text_to_video",
            weights=RouteWeights(quality=0.8, cost=0.1, speed=0.1),
        )
        h = HealthTracker()
        s_hi = score_provider(p_hi, req, h.get("hi"))
        s_lo = score_provider(p_lo, req, h.get("lo"))
        assert s_hi > s_lo

    def test_speed_weighted_higher(self) -> None:
        p_fast = _provider(id="fast", quality=0.5, latency=5, cost_s=0.10)
        p_slow = _provider(id="slow", quality=0.9, latency=120, cost_s=0.01)
        req = CapabilityRequest(
            capability="text_to_video",
            weights=RouteWeights(quality=0.1, cost=0.1, speed=0.8),
        )
        h = HealthTracker()
        s_fast = score_provider(p_fast, req, h.get("fast"))
        s_slow = score_provider(p_slow, req, h.get("slow"))
        assert s_fast > s_slow


class TestCircuitBreaker:
    def test_opens_after_threshold(self) -> None:
        h = HealthSnapshot(provider_id="p1")
        for _ in range(5):
            h.record_failure()
        assert h.circuit_open is True

    def test_stays_closed_below_threshold(self) -> None:
        h = HealthSnapshot(provider_id="p1")
        for _ in range(4):
            h.record_failure()
        assert h.circuit_open is False

    def test_success_resets(self) -> None:
        h = HealthSnapshot(provider_id="p1")
        for _ in range(4):
            h.record_failure()
        h.record_success()
        assert h.failures == 0
        assert h.circuit_open is False


class TestRouting:
    def test_routes_ordered_by_score(self) -> None:
        providers = [
            _provider(id="cheap", quality=0.3, cost_s=0.01),
            _provider(id="premium", quality=0.9, cost_s=0.10),
            _provider(id="mid", quality=0.6, cost_s=0.05),
        ]
        req = CapabilityRequest(
            capability="text_to_video",
            weights=RouteWeights(quality=0.7, cost=0.15, speed=0.15),
        )
        h = HealthTracker()
        chain = route(providers, req, h)
        assert len(chain) == 3
        assert chain[0].id == "premium"

    def test_excludes_ineligible(self) -> None:
        providers = [
            _provider(id="good", capabilities=["text_to_video"]),
            _provider(id="wrong", capabilities=["lipsync"]),
        ]
        req = CapabilityRequest(capability="text_to_video")
        h = HealthTracker()
        chain = route(providers, req, h)
        assert len(chain) == 1
        assert chain[0].id == "good"

    def test_empty_when_all_ineligible(self) -> None:
        providers = [_provider(id="x", capabilities=["lipsync"])]
        req = CapabilityRequest(capability="text_to_video")
        h = HealthTracker()
        assert route(providers, req, h) == []


class TestCostLedger:
    def test_records_and_totals(self) -> None:
        ledger = CostLedger()
        ledger.record(CostEntry(provider_id="p1", capability="t2v", units=5, unit_type="seconds", cost_usd=0.50))
        ledger.record(CostEntry(provider_id="p2", capability="t2v", units=3, unit_type="seconds", cost_usd=0.30))
        assert ledger.total_cost() == pytest.approx(0.80)

    def test_budget_check_passes(self) -> None:
        ledger = CostLedger()
        ledger.record(CostEntry(provider_id="p1", capability="t2v", units=5, unit_type="seconds", cost_usd=0.50))
        assert ledger.check_budget(0.30, budget_usd=1.00) is True

    def test_budget_check_fails(self) -> None:
        ledger = CostLedger()
        ledger.record(CostEntry(provider_id="p1", capability="t2v", units=5, unit_type="seconds", cost_usd=0.80))
        assert ledger.check_budget(0.30, budget_usd=1.00) is False

    def test_no_budget_always_passes(self) -> None:
        ledger = CostLedger()
        assert ledger.check_budget(999.0, budget_usd=None) is True

    def test_filter_by_episode(self) -> None:
        ledger = CostLedger()
        ledger.record(CostEntry(provider_id="p1", capability="t2v", units=5, unit_type="s", cost_usd=1.0, episode_id="ep1"))
        ledger.record(CostEntry(provider_id="p1", capability="t2v", units=5, unit_type="s", cost_usd=2.0, episode_id="ep2"))
        assert ledger.total_cost(episode_id="ep1") == pytest.approx(1.0)


class TestHealthTracker:
    def test_creates_snapshot_on_first_access(self) -> None:
        h = HealthTracker()
        snap = h.get("new-provider")
        assert snap.provider_id == "new-provider"
        assert snap.failures == 0

    def test_record_failure_delegates(self) -> None:
        h = HealthTracker()
        for _ in range(5):
            h.record_failure("p1")
        assert h.get("p1").circuit_open is True

    def test_record_success_delegates(self) -> None:
        h = HealthTracker()
        for _ in range(4):
            h.record_failure("p1")
        h.record_success("p1")
        assert h.get("p1").failures == 0
