"""Voice discovery on ElevenLabs' shared-voices library.

A faithful port of the v2 `VoiceManager.search_voices_with_ai`: an LLM turns a
free-text description ("una niña dulce y energética") into ElevenLabs search
params, then we query the public shared-voices API and return the top matches —
each with a `preview_url` so the UI can audition them before assigning one to a
character. No account mutation; assignment just stores the community voice id.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from videocreator.domain.ports import LLMPort
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderUnavailableError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_SHARED_VOICES_URL = "https://api.elevenlabs.io/v1/shared-voices"

# Same intent as the v2 prompt: map natural language → strict EL search params.
_PARSE_PROMPT = (
    "You map a natural-language voice description to ElevenLabs shared-voices "
    "search parameters. Return ONLY a JSON object with these optional keys:\n"
    '- "gender": exactly "male" or "female" (omit if unclear)\n'
    '- "age": exactly "young", "middle_aged" or "old" (omit if unclear)\n'
    '- "search_term": 1-2 general English keywords (e.g. "energetic", '
    '"epic narrator", "spanish boy") — do NOT over-specify.\n'
    "Never invent other keys. No markdown."
)


@dataclass(frozen=True, slots=True)
class VoiceOption:
    voice_id: str
    name: str
    preview_url: str | None
    description: str | None
    gender: str | None
    age: str | None
    accent: str | None
    language: str | None


class ElevenLabsVoiceSearch:
    """`VoiceSearchPort` implementation backed by ElevenLabs shared voices."""

    def __init__(self, settings: Settings, llm: LLMPort) -> None:
        self._settings = settings
        self._llm = llm

    async def search(self, *, query: str, limit: int = 6) -> list[VoiceOption]:
        if not self._settings.elevenlabs_api_key:
            raise ProviderUnavailableError("ELEVENLABS_API_KEY is not configured")
        params = await self._parse_query(query)
        params["page_size"] = 30
        headers = {"xi-api-key": self._settings.elevenlabs_api_key}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_SHARED_VOICES_URL, headers=headers, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ElevenLabs voice search failed: {exc}") from exc
        voices = resp.json().get("voices", [])
        return [_to_option(v) for v in voices[:limit]]

    async def _parse_query(self, query: str) -> dict[str, str | int]:
        """Best-effort LLM parse; degrade to a raw keyword search on any failure."""
        try:
            raw = await self._llm.complete(
                f"{_PARSE_PROMPT}\n\nDescription: {query}", temperature=0.2,
            )
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            data = json.loads(cleaned)
        except (ProviderError, ValueError, json.JSONDecodeError):
            data = {"search_term": query[:20]}
        params: dict[str, str | int] = {}
        if data.get("gender") in {"male", "female"}:
            params["gender"] = data["gender"]
        if data.get("age") in {"young", "middle_aged", "old"}:
            params["age"] = data["age"]
        if data.get("search_term"):
            params["search"] = str(data["search_term"])[:40]
        return params


def _to_option(v: dict) -> VoiceOption:  # type: ignore[type-arg]
    return VoiceOption(
        voice_id=str(v.get("voice_id", "")),
        name=str(v.get("name", "voz")),
        preview_url=v.get("preview_url"),
        description=(v.get("description") or None),
        gender=v.get("gender"),
        age=v.get("age"),
        accent=v.get("accent"),
        language=v.get("language"),
    )


__all__ = ["ElevenLabsVoiceSearch", "VoiceOption"]
