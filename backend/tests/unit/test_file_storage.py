"""Tests for LocalFileStorage — focus on path-traversal containment.

The traversal guard is security-critical: the `/storage/{bucket}/{key:path}`
REST endpoint feeds user-controlled keys straight into the storage layer, so a
key that escapes the storage root is an arbitrary-file-read (LFI). These tests
lock the containment behaviour against regression.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from videocreator.infrastructure.storage.file_storage import LocalFileStorage
from videocreator.shared.errors import ValidationError


@pytest.fixture()
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "store")


def test_legit_key_roundtrips(storage: LocalFileStorage) -> None:
    asyncio.run(storage.put("episodes", "ep1/final.mp4", b"data"))
    assert asyncio.run(storage.get("episodes", "ep1/final.mp4")) == b"data"


def test_nested_key_allowed(storage: LocalFileStorage) -> None:
    path = storage._resolve("episodes", "ep1/clips/clip_01.mp4")
    assert path.is_relative_to(storage._root)


@pytest.mark.parametrize(
    "key",
    [
        "C:/Windows/System32/drivers/etc/hosts",  # windows drive-letter (the LFI)
        "C:\\secret.key",
        "/etc/passwd",  # posix absolute
        "\\\\server\\share\\x",  # UNC
        "../../../secret.key",  # parent traversal
        "a/../../b",  # traversal after a legit segment
        "ep1/../../../../etc/shadow",
    ],
)
def test_traversal_keys_rejected(storage: LocalFileStorage, key: str) -> None:
    with pytest.raises(ValidationError):
        storage._resolve("episodes", key)


@pytest.mark.parametrize("bucket", ["..", "a/b", "a\\b", ".hidden", ""])
def test_unsafe_bucket_rejected(storage: LocalFileStorage, bucket: str) -> None:
    with pytest.raises(ValidationError):
        storage._resolve(bucket, "x.mp4")


def test_list_keys_rejects_traversal_prefix(storage: LocalFileStorage) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(storage.list_keys("episodes", "../.."))


def test_delete_prefix_rejects_traversal(storage: LocalFileStorage) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(storage.delete_prefix("episodes", "C:/Windows"))
