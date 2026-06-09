"""Tests for the LTX-Desktop discovery client (health + installed models).

The client talks to the local LTX-Desktop FastAPI backend; here every call is
respx-mocked so no real app needs to be running.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO

import httpx
import pytest
import respx

from videocreator.domain.value_objects import ImageRef, ScenePrompt
from videocreator.infrastructure.providers.ltx_desktop import (
    LtxDesktopClient,
    LtxDesktopProvider,
)
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderQuotaError

BASE = "http://localhost:8000"


class _FakeStorage:
    """Captures puts; open_path returns a real temp file for i2v seeding."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[str] = []

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        self.puts.append(f"{bucket}/{key}")
        return f"{bucket}/{key}"

    async def get(self, bucket: str, key: str) -> bytes:
        return b""

    async def open_path(self, bucket: str, key: str) -> Path:
        p = self.root / bucket / key
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b"ref")
        return p

    async def delete(self, bucket: str, key: str) -> None: ...
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        return f"file://{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        return []


def _settings() -> Settings:
    return Settings(ltx_desktop_url=BASE)  # type: ignore[arg-type]


def _models_specs_payload() -> dict:
    return {
        "local_models": [
            {
                "pipeline": "fast",
                "spec": {
                    "display_name": "LTX Fast (local)",
                    "supported_resolutions_durations": {
                        "720p": {"fps_to_durations": {"24": [5, 8]}},
                        "1080p": {"fps_to_durations": {"24": [5, 8, 10]}},
                    },
                },
            }
        ],
        "api_models": [
            {
                "pipeline": "pro",
                "spec": {
                    "display_name": "LTX Pro (cloud)",
                    "supported_resolutions_durations": {
                        "1080p": {"fps_to_durations": {"24": [5]}},
                    },
                },
            }
        ],
    }


@respx.mock
async def test_is_up_true_on_healthy_backend() -> None:
    # Arrange
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"ok": True}))

    # Act
    up = await LtxDesktopClient(BASE).is_up()

    # Assert
    assert up is True


@respx.mock
async def test_is_up_false_when_unreachable() -> None:
    # Arrange — simulate the app not running
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))

    # Act
    up = await LtxDesktopClient(BASE).is_up()

    # Assert — degrade quietly, never raise
    assert up is False


@respx.mock
async def test_list_models_parses_local_and_api_models() -> None:
    # Arrange
    respx.get(f"{BASE}/api/generate/models-specs").mock(
        return_value=httpx.Response(200, json=_models_specs_payload())
    )

    # Act
    models = await LtxDesktopClient(BASE).list_models()

    # Assert
    assert [m.id for m in models] == ["fast", "pro"]
    fast = models[0]
    assert fast.display_name == "LTX Fast (local)"
    assert fast.source == "local"
    assert fast.max_duration_s == 10  # max across all resolutions/fps
    assert set(fast.resolutions) == {"720p", "1080p"}
    assert models[1].source == "api"


@respx.mock
async def test_list_models_raises_on_http_error() -> None:
    # Arrange
    respx.get(f"{BASE}/api/generate/models-specs").mock(return_value=httpx.Response(500))

    # Act / Assert — surfaces so the catalog can say "up but no models"
    with pytest.raises(httpx.HTTPError):
        await LtxDesktopClient(BASE).list_models()


@respx.mock
async def test_generate_text_to_video_returns_path() -> None:
    # Arrange
    route = respx.post(f"{BASE}/api/generate").mock(
        return_value=httpx.Response(200, json={"status": "complete", "video_path": "/out/v.mp4"})
    )

    # Act
    path = await LtxDesktopClient(BASE).generate(prompt="a cat", model="fast", duration=8)

    # Assert
    assert path == "/out/v.mp4"
    body = json.loads(route.calls.last.request.content)
    assert body["prompt"] == "a cat"
    assert body["model"] == "fast"
    assert body["duration"] == 8
    assert "imagePath" not in body  # text-to-video


@respx.mock
async def test_generate_image_to_video_sets_image_path() -> None:
    # Arrange
    route = respx.post(f"{BASE}/api/generate").mock(
        return_value=httpx.Response(200, json={"status": "complete", "video_path": "/out/i.mp4"})
    )

    # Act
    await LtxDesktopClient(BASE).generate(prompt="next", image_path="/frames/last.png")

    # Assert — image_path switches the app to image-to-video
    assert json.loads(route.calls.last.request.content)["imagePath"] == "/frames/last.png"


@respx.mock
async def test_generate_maps_payment_required_to_quota_error() -> None:
    # Arrange
    respx.post(f"{BASE}/api/generate").mock(return_value=httpx.Response(402))

    # Act / Assert
    with pytest.raises(ProviderQuotaError):
        await LtxDesktopClient(BASE).generate(prompt="x")


@respx.mock
async def test_generate_raises_on_cancelled() -> None:
    # Arrange
    respx.post(f"{BASE}/api/generate").mock(
        return_value=httpx.Response(200, json={"status": "cancelled"})
    )

    # Act / Assert
    with pytest.raises(ProviderError):
        await LtxDesktopClient(BASE).generate(prompt="x")


# ============================================================================
# LtxDesktopProvider (VideoProviderPort adapter)
# ============================================================================
@respx.mock
async def test_provider_generate_clip_stores_artifact(tmp_path: Path) -> None:
    # Arrange — the app "renders" to a local file the adapter must ingest
    rendered = tmp_path / "ltx_out.mp4"
    rendered.write_bytes(b"video")
    route = respx.post(f"{BASE}/api/generate").mock(
        return_value=httpx.Response(200, json={"status": "complete", "video_path": str(rendered)})
    )
    provider = LtxDesktopProvider(_settings(), _FakeStorage(tmp_path))  # type: ignore[arg-type]

    # Act
    clip = await provider.generate_clip(ScenePrompt(visual_prompt="a cat", duration_s=6), refs=[])

    # Assert — clip stored under the shared clip bucket, no i2v for a bare prompt
    assert clip.storage_key.startswith("episode-artifacts/ltx/")
    assert clip.provider_name == "ltx"
    assert clip.duration_s == 6
    assert "imagePath" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_provider_generate_clip_uses_ref_as_image_to_video(tmp_path: Path) -> None:
    # Arrange
    rendered = tmp_path / "ltx_out.mp4"
    rendered.write_bytes(b"video")
    route = respx.post(f"{BASE}/api/generate").mock(
        return_value=httpx.Response(200, json={"status": "complete", "video_path": str(rendered)})
    )
    provider = LtxDesktopProvider(_settings(), _FakeStorage(tmp_path))  # type: ignore[arg-type]
    refs = [ImageRef(storage_key="references/char.png")]

    # Act
    await provider.generate_clip(ScenePrompt(visual_prompt="next"), refs=refs)

    # Assert — a reference image switches the app to image-to-video
    assert "imagePath" in json.loads(route.calls.last.request.content)


@respx.mock
async def test_provider_availability_reports_models(tmp_path: Path) -> None:
    # Arrange
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(f"{BASE}/api/generate/models-specs").mock(
        return_value=httpx.Response(200, json=_models_specs_payload())
    )
    provider = LtxDesktopProvider(_settings(), _FakeStorage(tmp_path))  # type: ignore[arg-type]

    # Act
    health = await provider.availability()

    # Assert
    assert health.available is True
    assert health.name == "ltx"


async def test_provider_with_context_picks_model_hint(tmp_path: Path) -> None:
    # Arrange
    provider = LtxDesktopProvider(_settings(), _FakeStorage(tmp_path))  # type: ignore[arg-type]

    # Act — routing hints carry the chosen model
    provider.with_context(prefer_models=("pro",), style_profile=None, budget_usd=None)

    # Assert
    assert provider._model == "pro"
