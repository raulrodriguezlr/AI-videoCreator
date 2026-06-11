"""Tests for the ElevenLabs shared-voices search adapter (ported from v2)."""
from __future__ import annotations

from dataclasses import asdict

import httpx
import pytest
import respx

from videocreator.infrastructure.providers.elevenlabs_voices import (
    ElevenLabsVoiceSearch,
    VoiceOption,
)
from videocreator.interfaces.rest.schemas import VoiceOptionResponse
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderUnavailableError

_URL = "https://api.elevenlabs.io/v1/shared-voices"


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompt = ""

    async def complete(self, prompt: str, **_: object) -> str:
        self.prompt = prompt
        return self.reply


def _settings() -> Settings:
    return Settings(elevenlabs_api_key="test-key")  # type: ignore[call-arg]


@respx.mock
async def test_search_parses_query_and_returns_options() -> None:
    route = respx.get(_URL).mock(return_value=httpx.Response(200, json={"voices": [
        {"voice_id": "v1", "name": "Lucía", "preview_url": "http://x/1.mp3",
         "description": "sweet", "gender": "female", "age": "young"},
        {"voice_id": "v2", "name": "Diego", "preview_url": "http://x/2.mp3"},
    ]}))
    llm = _FakeLLM('{"gender": "female", "age": "young", "search_term": "energetic"}')

    options = await ElevenLabsVoiceSearch(_settings(), llm).search(query="niña dulce")  # type: ignore[arg-type]

    assert [o.voice_id for o in options] == ["v1", "v2"]
    assert options[0].preview_url == "http://x/1.mp3"
    sent = route.calls.last.request
    assert b"gender=female" in sent.url.query
    assert b"search=energetic" in sent.url.query


@respx.mock
async def test_search_degrades_when_llm_returns_garbage() -> None:
    route = respx.get(_URL).mock(return_value=httpx.Response(200, json={"voices": []}))
    llm = _FakeLLM("not json at all")

    await ElevenLabsVoiceSearch(_settings(), llm).search(query="abuelo grave")  # type: ignore[arg-type]

    # Falls back to a raw keyword search rather than failing.
    assert b"search=abuelo" in route.calls.last.request.url.query


async def test_search_requires_api_key() -> None:
    llm = _FakeLLM("{}")
    uc = ElevenLabsVoiceSearch(Settings(elevenlabs_api_key=None), llm)  # type: ignore[call-arg,arg-type]
    with pytest.raises(ProviderUnavailableError, match="ELEVENLABS_API_KEY"):
        await uc.search(query="x")


def test_voice_option_serializes_to_response() -> None:
    """`VoiceOption` is a `slots=True` dataclass — it has no `__dict__`, so the
    REST router must use `dataclasses.asdict()` (not `vars()`, which raises
    `TypeError` on slotted dataclasses) to build `VoiceOptionResponse`."""
    option = VoiceOption(
        voice_id="v1", name="Lucía", preview_url="http://x/1.mp3",
        description="sweet", gender="female", age="young",
        accent="neutral", language="es",
    )

    with pytest.raises(TypeError, match="__dict__"):
        vars(option)  # the bug: this is what the route used to call

    response = VoiceOptionResponse(**asdict(option))

    assert response.voice_id == "v1"
    assert response.name == "Lucía"
    assert response.language == "es"
