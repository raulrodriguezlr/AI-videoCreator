"""Tests for YouTube publisher — fake service, no googleapiclient needed."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from videocreator.infrastructure.publish.youtube_publisher import (
    UploadResult,
    YouTubePublisher,
    build_credentials,
)
from videocreator.shared.errors import ProviderError


class _FakeInsert:
    def __init__(self, recorder: dict[str, Any], response: dict[str, Any]) -> None:
        self._recorder = recorder
        self._response = response

    def execute(self) -> dict[str, Any]:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeVideos:
    def __init__(self, recorder: dict[str, Any], response: Any) -> None:
        self._recorder = recorder
        self._response = response

    def insert(self, **kwargs: Any) -> _FakeInsert:
        self._recorder.update(kwargs)
        return _FakeInsert(self._recorder, self._response)


class _FakeService:
    def __init__(self, recorder: dict[str, Any], response: Any) -> None:
        self._videos = _FakeVideos(recorder, response)

    def videos(self) -> _FakeVideos:
        return self._videos


def _publisher(recorder: dict[str, Any], response: Any) -> YouTubePublisher:
    return YouTubePublisher(service_factory=lambda: _FakeService(recorder, response))


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "short.mp4"
    p.write_bytes(b"\x00\x00")
    return p


class TestUpload:
    def test_happy_path(self, video_file: Path, monkeypatch) -> None:
        monkeypatch.setattr(YouTubePublisher, "_media_upload",
                            staticmethod(lambda path: object()))
        recorder: dict[str, Any] = {}
        pub = _publisher(recorder, {"id": "yt-abc"})
        result = pub.upload(video_file, title="My Short", tags=("ai", "shorts"))
        assert result == UploadResult(
            video_id="yt-abc", url="https://www.youtube.com/watch?v=yt-abc")
        assert recorder["body"]["snippet"]["title"] == "My Short"
        assert recorder["body"]["status"]["privacyStatus"] == "private"
        assert recorder["body"]["status"]["selfDeclaredMadeForKids"] is False

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        pub = _publisher({}, {"id": "x"})
        with pytest.raises(FileNotFoundError):
            pub.upload(tmp_path / "nope.mp4", title="t")

    def test_empty_title_raises(self, video_file: Path) -> None:
        pub = _publisher({}, {"id": "x"})
        with pytest.raises(ValueError):
            pub.upload(video_file, title="   ")

    def test_bad_privacy_raises(self, video_file: Path) -> None:
        pub = _publisher({}, {"id": "x"})
        with pytest.raises(ValueError):
            pub.upload(video_file, title="t", privacy="secret")

    def test_api_error_wrapped(self, video_file: Path, monkeypatch) -> None:
        monkeypatch.setattr(YouTubePublisher, "_media_upload",
                            staticmethod(lambda path: object()))
        pub = _publisher({}, RuntimeError("quota exceeded"))
        with pytest.raises(ProviderError):
            pub.upload(video_file, title="t")


class _FakeQuery:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def execute(self) -> dict[str, Any]:
        return self._response


class _FakeReports:
    def __init__(self, recorder: dict[str, Any], response: dict[str, Any]) -> None:
        self._recorder = recorder
        self._response = response

    def query(self, **kwargs: Any) -> _FakeQuery:
        self._recorder.update(kwargs)
        return _FakeQuery(self._response)


class _FakeAnalytics:
    def __init__(self, recorder: dict[str, Any], response: dict[str, Any]) -> None:
        self._reports = _FakeReports(recorder, response)

    def reports(self) -> _FakeReports:
        return self._reports


class TestMetricsQuery:
    def test_rows_mapped_to_dicts(self) -> None:
        recorder: dict[str, Any] = {}
        response = {
            "columnHeaders": [{"name": "video"}, {"name": "day"}, {"name": "views"}],
            "rows": [["abc", "2026-06-01", 500]],
        }
        pub = YouTubePublisher(
            analytics_factory=lambda: _FakeAnalytics(recorder, response))
        rows = pub.query_metrics(start_date="2026-06-01", end_date="2026-06-07",
                                 video_ids=("abc",))
        assert rows == [{"video": "abc", "day": "2026-06-01", "views": 500}]
        assert recorder["filters"] == "video==abc"
        assert "audienceWatchRatio" in recorder["metrics"]


class TestBuildCredentials:
    """Token hygiene: `build_credentials` eagerly refreshes on construction so
    a revoked/expired refresh token surfaces here, not deep inside an upload.
    `Credentials.refresh` is monkeypatched — no real Google network call."""

    def test_refreshes_and_returns_fresh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from google.oauth2.credentials import Credentials

        def fake_refresh(self: Credentials, request: Any) -> None:
            self.token = "fresh-access-token"  # noqa: S105 - test fixture value

        monkeypatch.setattr(Credentials, "refresh", fake_refresh)

        creds = build_credentials(refresh_token="rt", client_id="cid", client_secret="cs")

        assert creds.token == "fresh-access-token"

    def test_refresh_failure_wrapped_in_provider_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from google.oauth2.credentials import Credentials

        def fake_refresh(self: Credentials, request: Any) -> None:
            raise RuntimeError("invalid_grant: token revoked")

        monkeypatch.setattr(Credentials, "refresh", fake_refresh)

        with pytest.raises(ProviderError, match="refresh failed"):
            build_credentials(refresh_token="rt", client_id="cid", client_secret="cs")
