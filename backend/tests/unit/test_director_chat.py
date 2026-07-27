"""Tests for Director's Chat — pure JSON Patch + LLM use case with fakes."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.director_chat import (
    DirectorChatUseCase,
    JsonPatchError,
    apply_json_patch,
)
from videocreator.domain.value_objects import DagNode, DagSpec


def _spec() -> DagSpec:
    return DagSpec(nodes=(
        DagNode(id="a", capability="llm_text", params={"duration_s": 10}),
        DagNode(id="b", capability="render", depends_on=("a",)),
    ))


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


class TestApplyJsonPatch:
    def test_replace(self) -> None:
        doc = {"nodes": [{"id": "a", "params": {"duration_s": 10}}]}
        out = apply_json_patch(doc, [
            {"op": "replace", "path": "/nodes/0/params/duration_s", "value": 20}])
        assert out["nodes"][0]["params"]["duration_s"] == 20
        assert doc["nodes"][0]["params"]["duration_s"] == 10  # original untouched

    def test_add_append_to_array(self) -> None:
        doc = {"nodes": [1]}
        out = apply_json_patch(doc, [{"op": "add", "path": "/nodes/-", "value": 2}])
        assert out["nodes"] == [1, 2]

    def test_add_dict_key(self) -> None:
        out = apply_json_patch({"x": {}}, [
            {"op": "add", "path": "/x/y", "value": 5}])
        assert out["x"]["y"] == 5

    def test_remove_array_element(self) -> None:
        out = apply_json_patch({"nodes": [1, 2, 3]}, [
            {"op": "remove", "path": "/nodes/1"}])
        assert out["nodes"] == [1, 3]

    def test_escaped_pointer_tokens(self) -> None:
        out = apply_json_patch({"a/b": {"~c": 1}}, [
            {"op": "replace", "path": "/a~1b/~0c", "value": 2}])
        assert out["a/b"]["~c"] == 2

    def test_unsupported_op_raises(self) -> None:
        with pytest.raises(JsonPatchError):
            apply_json_patch({}, [{"op": "move", "path": "/a", "from": "/b"}])

    def test_bad_index_raises(self) -> None:
        with pytest.raises(JsonPatchError):
            apply_json_patch({"n": [1]}, [{"op": "remove", "path": "/n/9"}])

    def test_missing_key_raises(self) -> None:
        with pytest.raises(JsonPatchError):
            apply_json_patch({}, [{"op": "replace", "path": "/nope", "value": 1}])


class TestDirectorChat:
    @pytest.mark.asyncio
    async def test_applies_patch_and_revalidates(self) -> None:
        response = json.dumps({
            "patch": [{"op": "replace", "path": "/nodes/0/params/duration_s",
                       "value": 20}],
            "explanation": "duration bumped",
        })
        uc = DirectorChatUseCase(FakeLLM([response]))  # type: ignore[arg-type]
        result = await uc.execute(_spec(), "make it 20 seconds")
        assert result.spec.nodes[0].params["duration_s"] == 20
        assert result.explanation == "duration bumped"
        assert len(result.patch) == 1

    @pytest.mark.asyncio
    async def test_empty_patch_is_noop(self) -> None:
        response = json.dumps({"patch": [], "explanation": "nothing to change"})
        uc = DirectorChatUseCase(FakeLLM([response]))  # type: ignore[arg-type]
        result = await uc.execute(_spec(), "looks good")
        assert result.spec == _spec()

    @pytest.mark.asyncio
    async def test_invalid_dag_patch_retries_then_succeeds(self) -> None:
        # First patch creates a dependency on an unknown node → DagSpec rejects.
        bad = json.dumps({"patch": [
            {"op": "replace", "path": "/nodes/1/depends_on", "value": ["ghost"]}],
            "explanation": "bad"})
        good = json.dumps({"patch": [], "explanation": "ok"})
        llm = FakeLLM([bad, good])
        uc = DirectorChatUseCase(llm)  # type: ignore[arg-type]
        result = await uc.execute(_spec(), "change deps")
        assert llm.calls == 2
        assert result.explanation == "ok"

    @pytest.mark.asyncio
    async def test_raises_after_two_failures(self) -> None:
        uc = DirectorChatUseCase(FakeLLM(["not json"]))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute(_spec(), "anything")

    @pytest.mark.asyncio
    async def test_markdown_fenced_response(self) -> None:
        response = "```json\n" + json.dumps(
            {"patch": [], "explanation": "fine"}) + "\n```"
        uc = DirectorChatUseCase(FakeLLM([response]))  # type: ignore[arg-type]
        result = await uc.execute(_spec(), "hi")
        assert result.explanation == "fine"
