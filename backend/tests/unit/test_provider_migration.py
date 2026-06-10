"""§15 Fase A fire test — the 3 legacy providers load through the SDK registry."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml")

from videocreator.infrastructure.providers.sdk.adapter_base import AdapterBase
from videocreator.infrastructure.providers.sdk.port_bridge import VideoPortBridge
from videocreator.infrastructure.providers.sdk.registry import ProviderRegistry

PROVIDERS_DIR = Path(__file__).resolve().parents[2] / "providers.d"

MIGRATED = ("artlist", "elevenlabs-studio", "ltx-desktop")


@pytest.fixture(scope="module")
def registry() -> ProviderRegistry:
    reg = ProviderRegistry(PROVIDERS_DIR)
    reg.discover()
    return reg


class TestMigration:
    def test_all_migrated_providers_load(self, registry: ProviderRegistry) -> None:
        for pid in MIGRATED:
            assert pid in registry.provider_ids, f"{pid} failed to load"

    def test_adapters_are_port_bridges(self, registry: ProviderRegistry) -> None:
        for pid in MIGRATED:
            loaded = registry.get(pid)
            assert loaded is not None
            assert isinstance(loaded.adapter, AdapterBase)
            assert isinstance(loaded.adapter, VideoPortBridge)

    def test_ltx_is_free_local(self, registry: ProviderRegistry) -> None:
        ltx = registry.get("ltx-desktop")
        assert ltx is not None
        assert ltx.adapter.estimate_cost(10.0) == 0.0
        assert "local" in ltx.manifest.tags

    def test_cloud_providers_cost_money(self, registry: ProviderRegistry) -> None:
        for pid in ("artlist", "elevenlabs-studio"):
            loaded = registry.get(pid)
            assert loaded is not None
            assert loaded.adapter.estimate_cost(10.0) > 0.0

    def test_find_by_capability_includes_migrated(
        self, registry: ProviderRegistry,
    ) -> None:
        t2v = {lp.manifest.id for lp in registry.find("text_to_video")}
        assert set(MIGRATED) <= t2v

    def test_free_constraint_excludes_cloud(self, registry: ProviderRegistry) -> None:
        free = {
            lp.manifest.id
            for lp in registry.find("text_to_video", max_cost_usd=0.0, duration_s=10)
        }
        assert "ltx-desktop" in free
        assert "artlist" not in free
