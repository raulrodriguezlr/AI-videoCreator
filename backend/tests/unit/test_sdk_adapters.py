"""Tests for the openapi, http_webhook, and comfyui_workflow SDK adapters.

No real network calls are made: each adapter's `_client()` is monkeypatched to
return an `httpx.AsyncClient` wired to an `httpx.MockTransport`.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest, GenResult
from videocreator.infrastructure.providers.sdk.adapter_comfyui import ComfyUiAdapter
from videocreator.infrastructure.providers.sdk.adapter_openapi import OpenApiAdapter
from videocreator.infrastructure.providers.sdk.adapter_webhook import WebhookAdapter
from videocreator.infrastructure.providers.sdk.manifest import (
    AdapterSpec,
    LatencyProfile,
    ProviderManifest,
)
from videocreator.shared.errors import ProviderError, ProviderTimeoutError

yaml = pytest.importorskip("yaml")

from videocreator.infrastructure.providers.sdk.registry import ProviderRegistry  # noqa: E402


def _manifest(adapter_type: str, config: dict, **kwargs) -> ProviderManifest:
    return ProviderManifest(
        id=kwargs.pop("id", "test"),
        name=kwargs.pop("name", "Test"),
        latency=kwargs.pop("latency", LatencyProfile(timeout_s=5)),
        adapter=AdapterSpec(type=adapter_type, config=config),
        **kwargs,
    )


# ---- WebhookAdapter --------------------------------------------------------
class TestWebhookAdapter:
    @pytest.mark.asyncio
    async def test_generate_json_video_url(self, tmp_path: Path) -> None:
        manifest = _manifest("http_webhook", {"url": "http://engine.local/generate"})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/generate":
                return httpx.Response(200, json={"video_url": "http://engine.local/result.mp4"})
            if request.url.path == "/result.mp4":
                return httpx.Response(
                    200, content=b"VIDEOBYTES", headers={"content-type": "video/mp4"}
                )
            return httpx.Response(404)

        adapter = WebhookAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        adapter._client = fake_client  # type: ignore[method-assign]

        result = await adapter.generate(GenRequest(prompt="a cat", duration_s=3))
        assert isinstance(result, GenResult)
        assert result.video_bytes == b"VIDEOBYTES"
        assert result.duration_s == 3
        assert result.metadata["adapter"] == "http_webhook"

    @pytest.mark.asyncio
    async def test_generate_raw_video_response(self, tmp_path: Path) -> None:
        manifest = _manifest("http_webhook", {"url": "http://engine.local/generate"})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"RAWBYTES", headers={"content-type": "video/mp4"})

        adapter = WebhookAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        adapter._client = fake_client  # type: ignore[method-assign]

        result = await adapter.generate(GenRequest(prompt="a dog"))
        assert result.video_bytes == b"RAWBYTES"

    @pytest.mark.asyncio
    async def test_generate_500_raises_provider_error(self, tmp_path: Path) -> None:
        manifest = _manifest("http_webhook", {"url": "http://engine.local/generate"})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        adapter = WebhookAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

        adapter._client = fake_client  # type: ignore[method-assign]

        with pytest.raises(ProviderError):
            await adapter.generate(GenRequest(prompt="fail"))

    @pytest.mark.asyncio
    async def test_health_default_when_no_health_url(self, tmp_path: Path) -> None:
        manifest = _manifest("http_webhook", {"url": "http://engine.local/generate"})
        adapter = WebhookAdapter(manifest=manifest, base_dir=tmp_path)
        h = await adapter.health()
        assert h["available"] is True


# ---- OpenApiAdapter ---------------------------------------------------------
class TestOpenApiAdapter:
    @pytest.mark.asyncio
    async def test_generate_synchronous(self, tmp_path: Path) -> None:
        manifest = _manifest(
            "openapi",
            {
                "base_url": "http://api.example.com",
                "generate_path": "/v1/generate",
                "field_map": {"prompt": "input_text", "duration_s": "duration"},
                "result_field": "video_url",
            },
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/generate":
                body = json.loads(request.content)
                assert body == {"input_text": "a robot", "duration": 4}
                return httpx.Response(
                    200, json={"video_url": "http://cdn.example.com/out.mp4"}
                )
            if request.url.host == "cdn.example.com":
                return httpx.Response(
                    200, content=b"CDNBYTES", headers={"content-type": "video/mp4"}
                )
            return httpx.Response(404)

        adapter = OpenApiAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url="http://api.example.com", transport=httpx.MockTransport(handler)
            )

        adapter._client = fake_client  # type: ignore[method-assign]

        result = await adapter.generate(GenRequest(prompt="a robot", duration_s=4))
        assert result.video_bytes == b"CDNBYTES"
        assert result.metadata["adapter"] == "openapi"

    @pytest.mark.asyncio
    async def test_generate_job_polling(self, tmp_path: Path) -> None:
        manifest = _manifest(
            "openapi",
            {
                "base_url": "http://api.example.com",
                "generate_path": "/v1/jobs",
                "field_map": {"prompt": "prompt"},
                "result_field": "url",
                "poll_path": "/v1/jobs/{id}",
                "poll_interval_s": 0,
            },
            latency=LatencyProfile(timeout_s=5),
        )

        calls = {"poll_count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/jobs" and request.method == "POST":
                return httpx.Response(200, json={"id": "job-123"})
            if request.url.path == "/v1/jobs/job-123":
                calls["poll_count"] += 1
                if calls["poll_count"] < 2:
                    return httpx.Response(200, json={"status": "running"})
                return httpx.Response(
                    200, json={"status": "done", "url": "http://cdn.example.com/done.mp4"}
                )
            if request.url.host == "cdn.example.com":
                return httpx.Response(
                    200, content=b"JOBBYTES", headers={"content-type": "video/mp4"}
                )
            return httpx.Response(404)

        adapter = OpenApiAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url="http://api.example.com", transport=httpx.MockTransport(handler)
            )

        adapter._client = fake_client  # type: ignore[method-assign]

        result = await adapter.generate(GenRequest(prompt="poll me"))
        assert result.video_bytes == b"JOBBYTES"
        assert calls["poll_count"] == 2

    @pytest.mark.asyncio
    async def test_generate_500_raises_provider_error(self, tmp_path: Path) -> None:
        manifest = _manifest(
            "openapi",
            {
                "base_url": "http://api.example.com",
                "generate_path": "/v1/generate",
                "field_map": {"prompt": "prompt"},
            },
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        adapter = OpenApiAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url="http://api.example.com", transport=httpx.MockTransport(handler)
            )

        adapter._client = fake_client  # type: ignore[method-assign]

        with pytest.raises(ProviderError):
            await adapter.generate(GenRequest(prompt="fail"))


# ---- ComfyUiAdapter ----------------------------------------------------------
def _write_workflow(tmp_path: Path, name: str = "workflow.json") -> Path:
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
        "9": {"class_type": "SaveAnimatedWEBP", "inputs": {}},
    }
    path = tmp_path / name
    path.write_text(json.dumps(workflow), encoding="utf-8")
    return path


class TestComfyUiAdapter:
    def test_workflow_prompt_and_seed_injection(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path)
        manifest = _manifest(
            "comfyui_workflow",
            {
                "workflow_file": "workflow.json",
                "prompt_node_id": "6",
                "prompt_field": "text",
                "seed_node_id": "3",
                "seed_field": "seed",
            },
        )
        adapter = ComfyUiAdapter(manifest=manifest, base_dir=tmp_path)

        injected = adapter._load_workflow(GenRequest(prompt="a sunset", seed=42))
        assert injected["6"]["inputs"]["text"] == "a sunset"
        assert injected["3"]["inputs"]["seed"] == 42
        # untouched nodes remain
        assert injected["3"]["inputs"]["steps"] == 20

    @pytest.mark.asyncio
    async def test_generate_happy_path(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path)
        manifest = _manifest(
            "comfyui_workflow",
            {
                "workflow_file": "workflow.json",
                "prompt_node_id": "6",
                "poll_interval_s": 0,
            },
            latency=LatencyProfile(timeout_s=5),
        )

        calls = {"history_count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/prompt" and request.method == "POST":
                body = json.loads(request.content)
                assert body["prompt"]["6"]["inputs"]["text"] == "a forest"
                return httpx.Response(200, json={"prompt_id": "abc123"})
            if request.url.path == "/history/abc123":
                calls["history_count"] += 1
                if calls["history_count"] < 2:
                    return httpx.Response(200, json={})
                return httpx.Response(
                    200,
                    json={
                        "abc123": {
                            "outputs": {
                                "9": {
                                    "videos": [
                                        {
                                            "filename": "out.webp",
                                            "subfolder": "",
                                            "type": "output",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                )
            if request.url.path == "/view":
                assert request.url.params["filename"] == "out.webp"
                return httpx.Response(
                    200, content=b"COMFYBYTES", headers={"content-type": "video/webp"}
                )
            return httpx.Response(404)

        adapter = ComfyUiAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url="http://127.0.0.1:8188", transport=httpx.MockTransport(handler)
            )

        adapter._client = fake_client  # type: ignore[method-assign]

        result = await adapter.generate(GenRequest(prompt="a forest"))
        assert result.video_bytes == b"COMFYBYTES"
        assert result.metadata["prompt_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_generate_poll_timeout_raises_provider_timeout(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path)
        manifest = _manifest(
            "comfyui_workflow",
            {
                "workflow_file": "workflow.json",
                "prompt_node_id": "6",
                "poll_interval_s": 0,
            },
            latency=LatencyProfile(timeout_s=0),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/prompt" and request.method == "POST":
                return httpx.Response(200, json={"prompt_id": "abc123"})
            if request.url.path == "/history/abc123":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        adapter = ComfyUiAdapter(manifest=manifest, base_dir=tmp_path)

        async def fake_client() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                base_url="http://127.0.0.1:8188", transport=httpx.MockTransport(handler)
            )

        adapter._client = fake_client  # type: ignore[method-assign]

        with pytest.raises(ProviderTimeoutError):
            await adapter.generate(GenRequest(prompt="never finishes"))

    def test_workflow_file_not_found(self, tmp_path: Path) -> None:
        manifest = _manifest(
            "comfyui_workflow",
            {"workflow_file": "missing.json", "prompt_node_id": "6"},
        )
        adapter = ComfyUiAdapter(manifest=manifest, base_dir=tmp_path)
        with pytest.raises(ProviderError):
            adapter._load_workflow(GenRequest(prompt="x"))


# ---- Registry wiring ---------------------------------------------------------
class TestRegistryAdapterTypes:
    def _write_manifest(self, tmp_path: Path, provider_id: str, adapter: dict) -> Path:
        provider_dir = tmp_path / provider_id
        provider_dir.mkdir()
        data = {
            "id": provider_id,
            "name": provider_id,
            "latency": {"timeout_s": 5},
            "adapter": adapter,
        }
        (provider_dir / "provider.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        return provider_dir

    def test_builds_http_webhook_adapter(self, tmp_path: Path) -> None:
        adapter = {"type": "http_webhook", "config": {"url": "http://engine.local/generate"}}
        self._write_manifest(tmp_path, "webhook-provider", adapter)

        reg = ProviderRegistry(tmp_path)
        count = reg.discover()
        assert count == 1
        lp = reg.get("webhook-provider")
        assert lp is not None
        assert isinstance(lp.adapter, WebhookAdapter)

    def test_builds_openapi_adapter(self, tmp_path: Path) -> None:
        adapter = {
            "type": "openapi",
            "config": {
                "base_url": "http://api.example.com",
                "generate_path": "/v1/generate",
                "field_map": {"prompt": "prompt"},
            },
        }
        self._write_manifest(tmp_path, "openapi-provider", adapter)

        reg = ProviderRegistry(tmp_path)
        count = reg.discover()
        assert count == 1
        lp = reg.get("openapi-provider")
        assert lp is not None
        assert isinstance(lp.adapter, OpenApiAdapter)

    def test_builds_comfyui_adapter(self, tmp_path: Path) -> None:
        adapter = {
            "type": "comfyui_workflow",
            "config": {"workflow_file": "workflow.json", "prompt_node_id": "6"},
        }
        provider_dir = self._write_manifest(tmp_path, "comfy-provider", adapter)
        _write_workflow(provider_dir)

        reg = ProviderRegistry(tmp_path)
        count = reg.discover()
        assert count == 1
        lp = reg.get("comfy-provider")
        assert lp is not None
        assert isinstance(lp.adapter, ComfyUiAdapter)
