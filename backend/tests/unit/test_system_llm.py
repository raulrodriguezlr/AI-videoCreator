"""Tests for runtime LLM config + Ollama administration."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from videocreator.infrastructure.system.ollama_admin import OllamaAdmin, is_valid_model_name
from videocreator.infrastructure.system.runtime_config import JsonRuntimeConfig
from videocreator.shared.config import Settings


# --------------------------------------------------------------------------
# JsonRuntimeConfig
# --------------------------------------------------------------------------
def test_runtime_config_roundtrip(tmp_path: Path) -> None:
    cfg = JsonRuntimeConfig(tmp_path / "runtime.json")

    cfg.set(llm_provider="ollama", ollama_model="qwen2.5:14b-instruct")

    assert cfg.get() == {"llm_provider": "ollama", "ollama_model": "qwen2.5:14b-instruct"}


def test_runtime_config_ignores_unknown_keys_and_none(tmp_path: Path) -> None:
    cfg = JsonRuntimeConfig(tmp_path / "runtime.json")

    cfg.set(llm_provider="gemini", bogus="x", gemini_model=None)  # type: ignore[arg-type]

    stored = cfg.get()
    assert stored == {"llm_provider": "gemini"}  # bogus dropped, None skipped


def test_runtime_config_missing_file_is_empty(tmp_path: Path) -> None:
    assert JsonRuntimeConfig(tmp_path / "absent.json").get() == {}


# --------------------------------------------------------------------------
# Model-name validation (shell-injection guard surface)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["qwen2.5:14b-instruct", "llama3.1:8b", "mistral-nemo", "a/b:c"])
def test_valid_model_names(name: str) -> None:
    assert is_valid_model_name(name)


@pytest.mark.parametrize("name", ["", "bad name", "model;rm -rf", "$(whoami)", "a|b"])
def test_invalid_model_names(name: str) -> None:
    assert not is_valid_model_name(name)


# --------------------------------------------------------------------------
# OllamaAdmin.status
# --------------------------------------------------------------------------
def _admin(tmp_path: Path) -> OllamaAdmin:
    return OllamaAdmin(Settings(), JsonRuntimeConfig(tmp_path / "runtime.json"))


@respx.mock
async def test_status_running_lists_models(tmp_path: Path) -> None:
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [
            {"name": "qwen2.5:14b-instruct"}, {"name": "llama3.1:8b"},
        ]})
    )
    status = await _admin(tmp_path).status()

    assert status["running"] is True
    assert status["models"] == ["llama3.1:8b", "qwen2.5:14b-instruct"]  # sorted


@respx.mock
async def test_status_down_when_unreachable(tmp_path: Path) -> None:
    respx.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("nope"))

    status = await _admin(tmp_path).status()

    assert status["running"] is False
    assert status["models"] == []


async def test_pull_rejects_bad_model_name(tmp_path: Path) -> None:
    admin = _admin(tmp_path)
    with pytest.raises(ValueError, match="invalid model name"):
        async for _ in admin.pull("evil; rm -rf /"):
            pass
