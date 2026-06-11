"""Capability executor — turns DagSpec nodes into real work (§16.10 runtime).

The DagExecutor is generic; this module supplies its NodeExecutor: a registry
mapping `node.capability` → async handler. Text/planning capabilities run
against the LLM; media capabilities resolve through the provider-SDK registry
(`find(capability)` → adapter.generate). A capability nobody implements fails
that node with a clear message — the DAG continues/cancels per its own rules,
the run never hangs.

Handlers receive (node, upstream_results) and return a JSON-able result that
downstream nodes can consume.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import DagNode
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

CapabilityHandler = Callable[[DagNode, dict[str, Any]], Awaitable[Any]]

_GENERIC_TEXT_PROMPT = """\
You are a video production assistant executing one pipeline step.

TASK: {task}
PARAMETERS: {params}
UPSTREAM RESULTS (from previous steps):
{upstream}

Produce the best possible output for this task. If the task implies
structured output, respond with JSON; otherwise plain text.
"""


class CapabilityExecutor:
    """NodeExecutor with a pluggable capability→handler registry."""

    def __init__(
        self,
        llm: LLMPort,
        *,
        provider_registry: Any = None,
        storage: Any = None,
    ) -> None:
        self._llm = llm
        self._registry = provider_registry
        self._storage = storage
        self._handlers: dict[str, CapabilityHandler] = {
            "llm_text": self._run_llm_text,
            "load_master": self._run_passthrough,
        }

    def register(self, capability: str, handler: CapabilityHandler) -> None:
        self._handlers[capability] = handler

    @property
    def capabilities(self) -> list[str]:
        return sorted(self._handlers)

    async def __call__(self, node: DagNode, upstream: dict[str, Any]) -> Any:
        handler = self._handlers.get(node.capability)
        if handler is not None:
            log.info("capexec.node", node=node.id, capability=node.capability)
            return await handler(node, upstream)
        if self._registry is not None:
            return await self._run_sdk_provider(node, upstream)
        raise RuntimeError(
            f"no handler or provider for capability '{node.capability}'"
        )

    # ---- built-in handlers --------------------------------------------------
    async def _run_passthrough(self, node: DagNode, upstream: dict[str, Any]) -> Any:
        return dict(node.params)

    async def _run_llm_text(self, node: DagNode, upstream: dict[str, Any]) -> str:
        params = dict(node.params)
        task = str(params.pop("task", "complete the step"))
        upstream_txt = json.dumps(upstream, ensure_ascii=False, default=str)[:4000]
        prompt = _GENERIC_TEXT_PROMPT.format(
            task=task, params=json.dumps(params, ensure_ascii=False),
            upstream=upstream_txt or "(none)",
        )
        return await self._llm.complete(prompt, temperature=0.7)

    async def _run_sdk_provider(self, node: DagNode, upstream: dict[str, Any]) -> Any:
        from videocreator.infrastructure.providers.sdk.adapter_base import GenRequest

        candidates = self._registry.find(node.capability)
        if not candidates:
            raise RuntimeError(
                f"no provider declares capability '{node.capability}' "
                f"(providers.d) — install one or register a handler"
            )
        prompt = str(node.params.get("prompt", ""))
        if not prompt:
            # fall back to the nearest upstream text result
            for value in upstream.values():
                if isinstance(value, str) and value.strip():
                    prompt = value[:2000]
                    break
        request = GenRequest(
            prompt=prompt,
            duration_s=float(node.params.get("duration_s", 5.0) or 5.0),
            seed=node.params.get("seed"),  # type: ignore[arg-type]
        )
        last_error: Exception | None = None
        for lp in candidates:
            try:
                result = await lp.adapter.generate(request)
                log.info("capexec.provider_done", node=node.id,
                         provider=lp.manifest.id)
                video_url = None
                if result.video_bytes and self._storage:
                    import uuid
                    key = f"runs/{node.id}_{uuid.uuid4().hex}.mp4"
                    await self._storage.put("media", key, result.video_bytes)
                    video_url = await self._storage.url_for("media", key)
                    
                return {
                    "provider": lp.manifest.id,
                    "duration_s": result.duration_s,
                    "width": result.width,
                    "height": result.height,
                    "bytes": len(result.video_bytes),
                    "video_url": video_url,
                    "metadata": result.metadata,
                }
            except Exception as e:
                last_error = e
                log.warning("capexec.provider_failed", node=node.id,
                            provider=lp.manifest.id, error=str(e))
        raise RuntimeError(
            f"all providers failed for '{node.capability}': {last_error}"
        )


__all__ = ["CapabilityExecutor", "CapabilityHandler"]
