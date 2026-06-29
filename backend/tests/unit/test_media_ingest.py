"""Ingestion tests — upload validation, URL detection, and the rights gate.

The actual yt-dlp network download is not exercised (no network in tests); the
fair-use/rights guard that protects it IS.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.infrastructure.publish.media_ingest import (
    ingest_youtube,
    is_youtube_url,
    save_upload,
)
from videocreator.shared.errors import ValidationError


def test_detects_youtube_urls() -> None:
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://vimeo.com/123")
    assert not is_youtube_url("not a url")


def test_save_upload_writes_file(tmp_path: Path) -> None:
    out = save_upload(b"\x00\x01\x02", tmp_path, filename="clip.mp4")
    assert out.exists() and out.read_bytes() == b"\x00\x01\x02"


def test_save_upload_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        save_upload(b"", tmp_path)


def test_save_upload_rejects_bad_extension(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        save_upload(b"data", tmp_path, filename="evil.exe")


def test_youtube_requires_rights_ack(tmp_path: Path) -> None:
    # Default: no ack -> blocked BEFORE any download attempt.
    with pytest.raises(ValidationError, match="rights"):
        ingest_youtube("https://youtu.be/abc", tmp_path)


def test_youtube_rejects_non_youtube_url(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="YouTube"):
        ingest_youtube("https://vimeo.com/1", tmp_path, rights_ack=True)
