"""Unit tests for HookRewriteUseCase — fake LLM, no external calls."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.hook_rewrite import (
    ANGLES,
    HookRewriteUseCase,
    HookVariant,
    cold_start_hook_policy,
    recommend_hook,
)
from videocreator.domain.entities import Scene, Script
from videocreator.shared.ids import PodId, ScriptId, TopicId, new_scene_id, new_script_id


# ---- fakes ----------------------------------------------------------------
class FakeLLM:
    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_idx = 0

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str:
        if self._responses:
            resp = self._responses[self._call_idx % len(self._responses)]
            self._call_idx += 1
            return resp
        return json.dumps({
            "hook_text": "Wait until you see this",
            "rationale": "curiosity gap"
        })


class FakeScriptRepo:
    def __init__(self, script: Script | None = None) -> None:
        self._script = script

    async def get(self, script_id: ScriptId) -> Script | None:
        return self._script

    async def list_for_pod(self, pod_id: PodId) -> list[Script]:
        return [self._script] if self._script else []

    async def save(self, script: Script) -> Script:
        return script


def _make_script(audio_text: str = "Once upon a time in a magical forest") -> Script:
    return Script(
        id=new_script_id(),
        pod_id=PodId("pod-1"),
        topic_id=TopicId("topic-1"),
        title="Test Episode",
        scenes=[
            Scene(
                id=new_scene_id(),
                index=0,
                visual_prompt="A magical forest at dawn",
                audio_text=audio_text,
            ),
            Scene(
                id=new_scene_id(),
                index=1,
                visual_prompt="A squirrel appears",
                audio_text="The squirrel looked around",
            ),
        ],
    )


# ---- tests ----------------------------------------------------------------
@pytest.mark.asyncio
async def test_generates_variants() -> None:
    script = _make_script()
    uc = HookRewriteUseCase(llm=FakeLLM(), scripts=FakeScriptRepo(script))  # type: ignore[arg-type]
    variants = await uc.execute(script.id, n_variants=3)
    assert len(variants) == 3
    assert all(isinstance(v, HookVariant) for v in variants)
    assert all(v.est_duration_s <= 2.5 for v in variants)


@pytest.mark.asyncio
async def test_rejects_too_long_hooks() -> None:
    long_hook = json.dumps({
        "hook_text": "This is a very long hook that has way too many words to be effective",
        "rationale": "too long"
    })
    script = _make_script()
    uc = HookRewriteUseCase(
        llm=FakeLLM(responses=[long_hook]),  # type: ignore[arg-type]
        scripts=FakeScriptRepo(script),  # type: ignore[arg-type]
    )
    variants = await uc.execute(script.id, n_variants=2)
    assert len(variants) == 0


@pytest.mark.asyncio
async def test_script_not_found_raises() -> None:
    uc = HookRewriteUseCase(llm=FakeLLM(), scripts=FakeScriptRepo(None))  # type: ignore[arg-type]
    with pytest.raises(Exception):
        await uc.execute(ScriptId("nonexistent"))


@pytest.mark.asyncio
async def test_empty_scenes_raises() -> None:
    script = Script(
        id=new_script_id(),
        pod_id=PodId("pod-1"),
        title="Empty",
        scenes=[],
    )
    uc = HookRewriteUseCase(llm=FakeLLM(), scripts=FakeScriptRepo(script))  # type: ignore[arg-type]
    with pytest.raises(Exception, match="no scenes"):
        await uc.execute(script.id)


@pytest.mark.asyncio
async def test_handles_malformed_llm_response() -> None:
    script = _make_script()
    uc = HookRewriteUseCase(
        llm=FakeLLM(responses=["not json at all"]),  # type: ignore[arg-type]
        scripts=FakeScriptRepo(script),  # type: ignore[arg-type]
    )
    variants = await uc.execute(script.id, n_variants=2)
    assert len(variants) == 0


def test_cold_start_policy() -> None:
    policy = cold_start_hook_policy()
    assert len(policy.arms) == len(ANGLES)
    assert policy.dimension == 4


def test_recommend_hook() -> None:
    variants = [
        HookVariant(angle=a, text=f"hook {a}", est_duration_s=1.5, rationale="test")
        for a in ANGLES
    ]
    policy = cold_start_hook_policy()
    context = [1.0, 0.0, 0.5, 0.2]
    chosen, decision = recommend_hook(variants, policy, context)
    assert chosen.angle == decision.arm_id
    assert chosen in variants
