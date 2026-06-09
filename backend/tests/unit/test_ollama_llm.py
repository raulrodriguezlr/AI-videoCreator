"""Adapter tests for the local Ollama LLM, using respx-mocked HTTP.

Verifies the transport contract (request shape, structured-output handling,
error mapping) without a running Ollama server.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from videocreator.infrastructure.llm.ollama_llm import OllamaLLM
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderUnavailableError

_GENERATE = "http://localhost:11434/api/generate"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"llm_provider": "ollama", "ollama_model": "qwen2.5:14b-instruct"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@respx.mock
async def test_complete_returns_response_field() -> None:
    route = respx.post(_GENERATE).mock(
        return_value=httpx.Response(200, json={"response": "hello world", "done": True})
    )
    llm = OllamaLLM(_settings())

    out = await llm.complete("say hi")

    assert out == "hello world"
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "qwen2.5:14b-instruct"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0.7
    assert "format" not in sent  # no schema → no forced json


@respx.mock
async def test_structured_output_forces_json_and_appends_schema() -> None:
    route = respx.post(_GENERATE).mock(
        return_value=httpx.Response(200, json={"response": '{"ok": true}'})
    )
    llm = OllamaLLM(_settings())
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    out = await llm.complete("give me json", response_schema=schema)

    assert out == '{"ok": true}'
    sent = json.loads(route.calls.last.request.content)
    assert sent["format"] == "json"
    assert "JSON Schema" in sent["prompt"]
    assert '"boolean"' in sent["prompt"]  # schema was rendered into the prompt


@respx.mock
async def test_model_override_wins_over_default() -> None:
    route = respx.post(_GENERATE).mock(
        return_value=httpx.Response(200, json={"response": "x"})
    )
    llm = OllamaLLM(_settings())

    await llm.complete("hi", model="llama3.1:8b")

    assert json.loads(route.calls.last.request.content)["model"] == "llama3.1:8b"


@respx.mock
async def test_connection_error_maps_to_unavailable() -> None:
    respx.post(_GENERATE).mock(side_effect=httpx.ConnectError("refused"))
    llm = OllamaLLM(_settings())

    with pytest.raises(ProviderUnavailableError, match="ollama serve"):
        await llm.complete("hi")


@respx.mock
async def test_autostart_serves_then_retries_on_connect_error() -> None:
    state = {"calls": 0, "served": False}

    def _side_effect(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"response": "ok"})

    respx.post(_GENERATE).mock(side_effect=_side_effect)

    async def _serve() -> None:
        state["served"] = True

    llm = OllamaLLM(_settings(), ensure_running=_serve)

    out = await llm.complete("hi")

    assert out == "ok"
    assert state["served"] is True  # auto-start was invoked
    assert state["calls"] == 2  # failed once, retried once


@respx.mock
async def test_missing_model_maps_to_unavailable_with_pull_hint() -> None:
    respx.post(_GENERATE).mock(return_value=httpx.Response(404, text="model not found"))
    llm = OllamaLLM(_settings(ollama_model="missing-model"))

    with pytest.raises(ProviderUnavailableError, match="ollama pull missing-model"):
        await llm.complete("hi")


@respx.mock
async def test_server_error_maps_to_provider_error() -> None:
    respx.post(_GENERATE).mock(return_value=httpx.Response(500, text="boom"))
    llm = OllamaLLM(_settings())

    with pytest.raises(ProviderError, match="ollama returned 500"):
        await llm.complete("hi")
