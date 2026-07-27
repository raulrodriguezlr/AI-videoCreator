"""Director's Chat — conversational edits over a render recipe (§16.15).

The LLM sees the current DagSpec as JSON and answers with a JSON Patch
(RFC 6902). The patch is applied with a dependency-free pure-Python
implementation (local-first: no `jsonpatch` install required), then the result
is re-validated by re-parsing the DagSpec — an invalid recipe never escapes.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import DagSpec
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_CHAT_PROMPT = """\
You are a video render pipeline director. The current recipe is a DAG of
capability nodes (JSON below). The user asks for a change in plain language.

CURRENT RECIPE:
{spec}

USER REQUEST:
{message}

Respond ONLY with a JSON object:
{{"patch": [<RFC 6902 JSON Patch operations>], "explanation": "<one sentence>"}}

Rules:
- Allowed ops: add, replace, remove
- Paths address the recipe document, e.g. "/nodes/2/params/duration_s"
- Use "/nodes/-" to append a new node
- Keep node ids unique and dependencies valid (no cycles, no unknown ids)
- If the request needs no change, return an empty patch array
"""


class JsonPatchError(ValueError):
    """A patch operation could not be applied."""


@dataclass(frozen=True)
class ChatResult:
    patch: tuple[dict[str, Any], ...]
    explanation: str
    spec: DagSpec


def apply_json_patch(document: dict[str, Any], patch: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply RFC 6902 add/replace/remove ops. Returns a new document.

    Minimal by design — the three ops the director needs. `test` / `move` /
    `copy` are rejected loudly rather than silently ignored.
    """
    doc = copy.deepcopy(document)
    for op in patch:
        kind = op.get("op")
        path = op.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise JsonPatchError(f"invalid path: {path!r}")
        tokens = [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]
        parent = _resolve(doc, tokens[:-1])
        last = tokens[-1]
        if kind == "add":
            _add(parent, last, op.get("value"))
        elif kind == "replace":
            _replace(parent, last, op.get("value"))
        elif kind == "remove":
            _remove(parent, last)
        else:
            raise JsonPatchError(f"unsupported op: {kind!r}")
    return doc


def _resolve(doc: Any, tokens: list[str]) -> Any:
    node = doc
    for t in tokens:
        if isinstance(node, list):
            node = node[_index(t, len(node))]
        elif isinstance(node, dict):
            if t not in node:
                raise JsonPatchError(f"path segment not found: {t!r}")
            node = node[t]
        else:
            raise JsonPatchError(f"cannot traverse into {type(node).__name__}")
    return node


def _index(token: str, length: int) -> int:
    try:
        idx = int(token)
    except ValueError as e:
        raise JsonPatchError(f"invalid array index: {token!r}") from e
    if not 0 <= idx < length:
        raise JsonPatchError(f"array index out of range: {idx}")
    return idx


def _add(parent: Any, key: str, value: Any) -> None:
    if isinstance(parent, list):
        if key == "-":
            parent.append(value)
        else:
            parent.insert(_index(key, len(parent) + 1), value)
    elif isinstance(parent, dict):
        parent[key] = value
    else:
        raise JsonPatchError(f"cannot add to {type(parent).__name__}")


def _replace(parent: Any, key: str, value: Any) -> None:
    if isinstance(parent, list):
        parent[_index(key, len(parent))] = value
    elif isinstance(parent, dict):
        if key not in parent:
            raise JsonPatchError(f"replace target missing: {key!r}")
        parent[key] = value
    else:
        raise JsonPatchError(f"cannot replace in {type(parent).__name__}")


def _remove(parent: Any, key: str) -> None:
    if isinstance(parent, list):
        del parent[_index(key, len(parent))]
    elif isinstance(parent, dict):
        if key not in parent:
            raise JsonPatchError(f"remove target missing: {key!r}")
        del parent[key]
    else:
        raise JsonPatchError(f"cannot remove from {type(parent).__name__}")


class DirectorChatUseCase:
    """One chat turn: recipe + user message → validated patched recipe."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(self, spec: DagSpec, message: str) -> ChatResult:
        # mode="json" turns tuples into lists — JSON Patch needs mutable arrays.
        spec_doc = spec.model_dump(mode="json")
        spec_json = json.dumps(spec_doc, ensure_ascii=False, indent=2)
        prompt = _CHAT_PROMPT.format(spec=spec_json, message=message)
        last_error = ""
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.3)
            decision = _parse_decision(raw)
            if decision is None:
                last_error = "unparseable LLM response"
                log.warning("director.parse_failed", attempt=attempt)
                continue
            patch = decision["patch"]
            try:
                new_doc = apply_json_patch(spec_doc, patch)
                new_spec = DagSpec.model_validate(new_doc)
            except (JsonPatchError, ValidationError) as e:
                last_error = str(e)
                log.warning("director.patch_invalid", attempt=attempt, error=last_error)
                continue
            log.info("director.chat.done", ops=len(patch), attempt=attempt)
            return ChatResult(
                patch=tuple(patch),
                explanation=str(decision.get("explanation", "")),
                spec=new_spec,
            )
        raise ValueError(f"director chat failed after 2 attempts: {last_error}")


def _parse_decision(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.split("\n") if not line.startswith("```"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("patch"), list):
        return None
    return data


__all__ = [
    "ChatResult",
    "DirectorChatUseCase",
    "JsonPatchError",
    "apply_json_patch",
]
