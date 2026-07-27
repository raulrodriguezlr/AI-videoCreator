"""Tests for §10.3 brand kits + §11.3 outbound webhooks + trace-id binding."""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.domain.services.brand_kit import BrandKit
from videocreator.infrastructure.filesystem.brand_kit_store import BrandKitStore
from videocreator.infrastructure.queue.outbound_webhooks import (
    WebhookDispatcher,
    WebhookTarget,
)


class TestBrandKit:
    def test_defaults_valid(self) -> None:
        kit = BrandKit(pod_id="p1")
        assert kit.primary_color == "#FFD400"
        assert kit.caption_style()["highlight"] == "#FFD400"

    def test_rejects_bad_hex(self) -> None:
        with pytest.raises(ValueError):
            BrandKit(pod_id="p1", primary_color="yellow")

    def test_prompt_fragment_includes_tone_and_brand(self) -> None:
        kit = BrandKit(pod_id="p1", writing_tone="sarcastic",
                       watermark_text="@mypod")
        frag = kit.prompt_fragment()
        assert "sarcastic" in frag and "@mypod" in frag


class TestBrandKitStore:
    def test_roundtrip(self, tmp_path: Path) -> None:
        store = BrandKitStore(tmp_path)
        kit = BrandKit(pod_id="p1", font_family="Inter", voice_id="v-9")
        store.save(kit)
        loaded = store.get("p1")
        assert loaded == kit

    def test_missing_is_none(self, tmp_path: Path) -> None:
        assert BrandKitStore(tmp_path).get("ghost") is None

    def test_corrupt_file_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "p1").mkdir()
        (tmp_path / "p1" / "brand_kit.json").write_text("{broken", encoding="utf-8")
        assert BrandKitStore(tmp_path).get("p1") is None

    def test_delete(self, tmp_path: Path) -> None:
        store = BrandKitStore(tmp_path)
        store.save(BrandKit(pod_id="p1"))
        assert store.delete("p1") is True
        assert store.delete("p1") is False


class TestWebhookDispatcher:
    @pytest.mark.asyncio
    async def test_delivers_to_subscribed_targets(self, monkeypatch) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register(WebhookTarget(url="https://hook.example/a"))
        dispatcher.register(WebhookTarget(
            url="https://hook.example/b", events=("other.event",)))

        sent: list[str] = []

        async def fake_deliver(target: WebhookTarget, event: str, body: bytes) -> bool:
            sent.append(target.url)
            return True

        monkeypatch.setattr(dispatcher, "_deliver", fake_deliver)
        delivered = await dispatcher.dispatch("render.completed", {"run_id": "r1"})
        assert delivered == 1
        assert sent == ["https://hook.example/a"]

    @pytest.mark.asyncio
    async def test_failed_delivery_never_raises(self, monkeypatch) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register(WebhookTarget(url="https://dead.example"))

        async def fake_deliver(target: WebhookTarget, event: str, body: bytes) -> bool:
            return False

        monkeypatch.setattr(dispatcher, "_deliver", fake_deliver)
        delivered = await dispatcher.dispatch("render.failed", {})
        assert delivered == 0


class TestTraceBinding:
    def test_bind_and_clear(self) -> None:
        import structlog

        from videocreator.shared.logging import bind_trace, clear_trace

        bind_trace("run-42", pod="p1")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["trace_id"] == "run-42"
        assert ctx["pod"] == "p1"
        clear_trace()
        assert structlog.contextvars.get_contextvars() == {}
