"""Tests for compose_short input collection (pure) — no ffmpeg."""
from __future__ import annotations

from videocreator.infrastructure.queue.compose_helpers import collect_media_inputs


class TestCollectMediaInputs:
    def test_videos_in_upstream_order_plus_audio(self) -> None:
        upstream = {
            "clip-1": {"storage_key": "media/runs/a.mp4", "provider": "veo-gemini"},
            "voice": {"audio_key": "media/runs/audio/v.mp3"},
            "clip-2": {"storage_key": "media/runs/b.mp4"},
        }
        videos, audio = collect_media_inputs(upstream)
        assert videos == ["media/runs/a.mp4", "media/runs/b.mp4"]
        assert audio == "media/runs/audio/v.mp3"

    def test_no_audio(self) -> None:
        videos, audio = collect_media_inputs(
            {"c": {"storage_key": "media/x.mp4"}})
        assert videos == ["media/x.mp4"] and audio is None

    def test_first_audio_wins(self) -> None:
        upstream = {
            "a1": {"audio_key": "media/1.mp3"},
            "a2": {"audio_key": "media/2.mp3"},
        }
        _, audio = collect_media_inputs(upstream)
        assert audio == "media/1.mp3"

    def test_non_dict_and_empty_ignored(self) -> None:
        upstream = {
            "text": "plain string result",
            "weird": {"storage_key": ""},
            "ok": {"storage_key": "media/v.mp4"},
        }
        videos, audio = collect_media_inputs(upstream)
        assert videos == ["media/v.mp4"] and audio is None

    def test_empty_upstream(self) -> None:
        assert collect_media_inputs({}) == ([], None)
