"""Brain agent — a minimal function-calling loop over an LLM with tools.

No framework: the LLM is asked to either call a tool (JSON) or answer.
Works with any LLMPort via a structured-prompt protocol, so it runs against
Gemini and Ollama alike without native function-calling support.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.infrastructure.brain.tools import ToolRegistry
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are the Viral Brain — an analyst agent for short-form video creators.
You investigate trends, analyze viral videos, and propose actionable formats.

You have these tools available:
{tools}

To use a tool, respond ONLY with JSON:
{{"tool": "<name>", "args": {{...}}}}

When you have enough information to answer the goal, respond ONLY with JSON:
{{"answer": "<your final answer>"}}

Conversation so far:
{history}

Goal: {goal}
"""

_MAX_RESULT_CHARS = 8000


@dataclass(frozen=True)
class AgentStep:
    """One step in the agent trace — tool call or final answer."""

    kind: str  # "tool_call" | "answer" | "error"
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: str | None = None


class BrainAgent:
    """Iterative tool-calling loop with bounded steps."""

    def __init__(self, llm: LLMPort, tools: ToolRegistry) -> None:
        self._llm = llm
        self._tools = tools

    async def run(self, goal: str, *, max_steps: int = 12) -> tuple[str, list[AgentStep]]:
        """Run the agent until it answers or exhausts max_steps.

        Returns (final_answer, trace).
        """
        history: list[str] = []
        trace: list[AgentStep] = []

        tools_desc = "\n".join(
            f"- {s['name']}: {s['description']} (args schema: {json.dumps(s['parameters'])})"
            for s in self._tools.schemas
        ) or "(no tools available)"

        for step_n in range(max_steps):
            prompt = _SYSTEM_PROMPT.format(
                tools=tools_desc,
                history="\n".join(history) or "(empty)",
                goal=goal,
            )
            raw = await self._llm.complete(prompt, temperature=0.3)
            decision = _parse_decision(raw)

            if decision is None:
                history.append(f"[invalid response, must be JSON]: {raw[:200]}")
                trace.append(AgentStep(kind="error", result=raw[:200]))
                continue

            if "answer" in decision:
                answer = str(decision["answer"])
                trace.append(AgentStep(kind="answer", result=answer))
                log.info("brain.answer", steps=step_n + 1)
                return answer, trace

            tool_name = decision.get("tool", "")
            args = decision.get("args", {}) or {}
            tool = self._tools.get(tool_name)

            if tool is None:
                history.append(f"[unknown tool '{tool_name}']")
                trace.append(AgentStep(kind="error", tool=tool_name))
                continue

            try:
                result = await tool.fn(**args)
                result_str = json.dumps(result, default=str)[:_MAX_RESULT_CHARS]
            except Exception as e:
                result_str = f"[tool error: {e}]"

            history.append(f"called {tool_name}({json.dumps(args)}) -> {result_str}")
            trace.append(
                AgentStep(kind="tool_call", tool=tool_name, args=args, result=result_str)
            )
            log.info("brain.tool_call", tool=tool_name, step=step_n + 1)

        log.warning("brain.max_steps", max_steps=max_steps)
        return "max_steps reached without final answer", trace


def _parse_decision(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and ("tool" in data or "answer" in data):
            return data
        return None
    except json.JSONDecodeError:
        return None


__all__ = ["AgentStep", "BrainAgent"]
