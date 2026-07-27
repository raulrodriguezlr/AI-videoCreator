"""Tests for Provider SDK — manifest parsing, registry discovery, adapter loading."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.infrastructure.providers.sdk.manifest import (
    AdapterSpec,
    AuthSpec,
    CostModel,
    LatencyProfile,
    ModelSpec,
    ProviderManifest,
)

yaml = pytest.importorskip("yaml")

from videocreator.infrastructure.providers.sdk.registry import (
    LoadedProvider,
    ProviderRegistry,
)


# ---- manifest tests -------------------------------------------------------
class TestManifest:
    def test_minimal_manifest(self) -> None:
        m = ProviderManifest(
            id="test", name="Test", adapter=AdapterSpec(type="python", entrypoint="a.py"),
        )
        assert m.id == "test"
        assert m.adapter.type == "python"
        assert m.cost.per_second_usd == 0.0

    def test_full_manifest(self) -> None:
        m = ProviderManifest(
            id="kling-3-omni",
            name="Kling 3.0 Omni",
            version="3.0",
            description="High-quality video generation",
            capabilities=["text_to_video", "image_to_video"],
            models=[
                ModelSpec(
                    id="kling-3.0",
                    family="kling",
                    capabilities=["text_to_video"],
                    max_duration_s=10,
                    cost=CostModel(per_second_usd=0.05),
                    latency=LatencyProfile(p50_s=30, p95_s=120),
                    strengths=["cinematic", "consistent"],
                ),
            ],
            cost=CostModel(per_second_usd=0.05, per_request_usd=0.10),
            latency=LatencyProfile(p50_s=30, p95_s=120, timeout_s=300),
            auth=AuthSpec(vault_key="kling_api_key"),
            adapter=AdapterSpec(type="python", entrypoint="adapters/kling.py"),
            tags=["premium", "cinematic"],
        )
        assert len(m.models) == 1
        assert m.models[0].id == "kling-3.0"
        assert m.auth is not None
        assert m.auth.vault_key == "kling_api_key"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(Exception):
            ProviderManifest(
                id="x", name="X",
                adapter=AdapterSpec(type="python", entrypoint="a.py"),
                bogus="field",
            )

    def test_from_yaml(self) -> None:
        raw = dedent("""\
            id: demo
            name: Demo Provider
            capabilities: [text_to_video]
            cost:
              per_second_usd: 0.02
            latency:
              p50_s: 10
              p95_s: 60
            adapter:
              type: python
              entrypoint: adapter.py
        """)
        data = yaml.safe_load(raw)
        m = ProviderManifest.model_validate(data)
        assert m.id == "demo"
        assert m.cost.per_second_usd == 0.02


# ---- adapter base tests ---------------------------------------------------
class TestAdapterBase:
    def test_estimate_cost(self) -> None:
        manifest = ProviderManifest(
            id="t", name="T",
            cost=CostModel(per_second_usd=0.05, per_request_usd=0.10),
            adapter=AdapterSpec(type="python", entrypoint="a.py"),
        )

        class DummyAdapter(AdapterBase):
            async def generate(self, request: GenRequest) -> GenResult:
                return GenResult(video_bytes=b"", duration_s=0, width=0, height=0)

        adapter = DummyAdapter(manifest=manifest, base_dir=Path("."))
        assert adapter.estimate_cost(10) == pytest.approx(0.60)
        assert adapter.provider_id == "t"

    @pytest.mark.asyncio
    async def test_default_health(self) -> None:
        manifest = ProviderManifest(
            id="h", name="Health Test",
            adapter=AdapterSpec(type="python", entrypoint="a.py"),
        )

        class DummyAdapter(AdapterBase):
            async def generate(self, request: GenRequest) -> GenResult:
                return GenResult(video_bytes=b"", duration_s=0, width=0, height=0)

        adapter = DummyAdapter(manifest=manifest, base_dir=Path("."))
        h = await adapter.health()
        assert h["available"] is True


# ---- registry tests -------------------------------------------------------
PROVIDERS_D = Path(__file__).resolve().parents[2] / "providers.d"


class TestRegistry:
    def test_discover_test_provider(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        count = reg.discover()
        assert count >= 1
        assert "test-provider" in reg.provider_ids

    def test_get_loaded_provider(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        lp = reg.get("test-provider")
        assert lp is not None
        assert isinstance(lp, LoadedProvider)
        assert lp.manifest.id == "test-provider"

    @pytest.mark.asyncio
    async def test_adapter_generate(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        lp = reg.get("test-provider")
        assert lp is not None
        result = await lp.adapter.generate(GenRequest(prompt="test", duration_s=5))
        assert isinstance(result, GenResult)
        assert result.duration_s == 5

    def test_find_by_capability(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        found = reg.find("text_to_video")
        assert len(found) >= 1
        assert any(lp.manifest.id == "test-provider" for lp in found)

    def test_find_missing_capability(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        found = reg.find("nonexistent_capability")
        assert len(found) == 0

    def test_find_by_tag(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        found = reg.find("text_to_video", tag="test")
        assert len(found) >= 1

    def test_reload(self) -> None:
        if not (PROVIDERS_D / "test-provider" / "provider.yaml").exists():
            pytest.skip("test-provider not in providers.d")
        reg = ProviderRegistry(PROVIDERS_D)
        reg.discover()
        count = reg.reload()
        assert count >= 1

    def test_empty_dir(self, tmp_path: Path) -> None:
        reg = ProviderRegistry(tmp_path)
        count = reg.discover()
        assert count == 0

    def test_missing_dir(self, tmp_path: Path) -> None:
        reg = ProviderRegistry(tmp_path / "nonexistent")
        count = reg.discover()
        assert count == 0
