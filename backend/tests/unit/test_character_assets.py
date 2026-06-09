"""Tests for the character reference-image use cases (asset manager).

Fakes over mocks: an in-memory storage and image generator let us assert the
real append/persist/delete behaviour without touching disk or the network.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pytest

from videocreator.application.use_cases.characters import (
    AddCharacterReferences,
    GenerateCharacterReference,
    RemoveCharacterReference,
)
from videocreator.domain.entities import LOCAL_USER_ID, Character, Pod, PodConfig
from videocreator.shared.errors import ForbiddenError, ValidationError
from videocreator.shared.ids import (
    CharacterId,
    UserId,
    new_character_id,
    new_pod_id,
)

OTHER = UserId("usr_other")


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        self.objects[f"{bucket}/{key}"] = data if isinstance(data, bytes) else data.read()
        return f"{bucket}/{key}"

    async def delete(self, bucket: str, key: str) -> None:
        self.objects.pop(f"{bucket}/{key}", None)

    # unused port methods
    async def get(self, bucket: str, key: str) -> bytes: return b""
    async def open_path(self, bucket: str, key: str) -> Path: return Path(key)
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str: return key
    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]: return []


class _FakeImages:
    def __init__(self, blobs: list[bytes]) -> None:
        self.blobs = blobs
        self.calls: list[str] = []

    async def generate(self, prompt: str, **_: object) -> list[bytes]:
        self.calls.append(prompt)
        return self.blobs


class _FakeCharRepo:
    def __init__(self, character: Character) -> None:
        self.store = {character.id: character}

    async def get(self, character_id: CharacterId) -> Character | None:
        return self.store.get(character_id)

    async def save(self, character: Character) -> Character:
        self.store[character.id] = character
        return character


class _FakePodRepo:
    def __init__(self, pod: Pod) -> None:
        self.pod = pod

    async def get(self, pod_id: object) -> Pod | None:
        return self.pod if pod_id == self.pod.id else None


def _fixture() -> tuple[_FakePodRepo, _FakeCharRepo, Character]:
    pod = Pod(id=new_pod_id(), owner_id=LOCAL_USER_ID, name="kids",
              config=PodConfig(series_name="Kids"))
    char = Character(id=new_character_id(), pod_id=pod.id, name="Tico")
    return _FakePodRepo(pod), _FakeCharRepo(char), char


async def test_upload_appends_refs_and_persists_bytes() -> None:
    pods, chars, char = _fixture()
    storage = _FakeStorage()
    uc = AddCharacterReferences(pods, chars, storage)  # type: ignore[arg-type]

    result = await uc.execute(
        character_id=char.id, requester_id=LOCAL_USER_ID,
        files=[(b"\x89PNG-1", "image/png"), (b"\xff\xd8-2", "image/jpeg")],
    )

    assert len(result.reference_image_keys) == 2
    assert all(r.startswith("references/") for r in result.reference_image_keys)
    assert result.reference_image_keys[0].endswith(".png")
    assert result.reference_image_keys[1].endswith(".jpg")
    assert len(storage.objects) == 2  # both blobs written


async def test_generate_calls_image_port_and_attaches() -> None:
    pods, chars, char = _fixture()
    storage = _FakeStorage()
    images = _FakeImages([b"generated-bytes"])
    uc = GenerateCharacterReference(pods, chars, storage, images)  # type: ignore[arg-type]

    result = await uc.execute(
        character_id=char.id, requester_id=LOCAL_USER_ID, prompt="Tico, pixar style",
    )

    assert images.calls == ["Tico, pixar style"]
    assert len(result.reference_image_keys) == 1
    assert len(storage.objects) == 1


async def test_generate_rejects_blank_prompt() -> None:
    pods, chars, char = _fixture()
    uc = GenerateCharacterReference(pods, chars, _FakeStorage(), _FakeImages([b"x"]))  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="must not be empty"):
        await uc.execute(character_id=char.id, requester_id=LOCAL_USER_ID, prompt="   ")


async def test_remove_detaches_and_deletes_from_storage() -> None:
    pods, chars, char = _fixture()
    storage = _FakeStorage()
    add = AddCharacterReferences(pods, chars, storage)  # type: ignore[arg-type]
    await add.execute(character_id=char.id, requester_id=LOCAL_USER_ID,
                      files=[(b"data", "image/png")])
    ref = chars.store[char.id].reference_image_keys[0]

    remove = RemoveCharacterReference(pods, chars, storage)  # type: ignore[arg-type]
    result = await remove.execute(character_id=char.id, requester_id=LOCAL_USER_ID, ref=ref)

    assert result.reference_image_keys == []
    assert storage.objects == {}  # blob deleted too


async def test_upload_rejects_foreign_owner() -> None:
    pods, chars, char = _fixture()
    uc = AddCharacterReferences(pods, chars, _FakeStorage())  # type: ignore[arg-type]

    with pytest.raises(ForbiddenError):
        await uc.execute(character_id=char.id, requester_id=OTHER,
                         files=[(b"data", "image/png")])
