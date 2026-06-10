"""Auto-benchmark harness — objective quality scoring for video providers.

Per prompt: generate clip → extract frames → score with CLIP similarity, OCR
match (if text expected), and LLM-judge. Per-dimension scores feed the
capability router's quality_score.

Heavy deps (open-clip, pytesseract) are lazy and optional — the harness
degrades to judge-only scoring when they're missing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from videocreator.domain.ports import LLMPort
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# Weighted blend per §16.9: CLIP 0.3, OCR 0.2 (when applicable), judge 0.5.
W_CLIP, W_OCR, W_JUDGE = 0.3, 0.2, 0.5

_JUDGE_PROMPT = """\
You are a video quality judge. The prompt used to generate the video was:
"{prompt}"

Frame descriptions (sampled from the video):
{frames}

Score 0-10 on: prompt adherence, visual artifacts (10 = none), temporal coherence.
Respond ONLY with JSON: {{"adherence": <n>, "artifacts": <n>, "coherence": <n>}}
"""


@dataclass(frozen=True)
class BenchmarkPrompt:
    id: str
    dimension: str
    prompt: str
    expected_text: str | None = None


@dataclass
class PromptScore:
    prompt_id: str
    dimension: str
    clip_score: float | None = None
    ocr_score: float | None = None
    judge_score: float | None = None

    @property
    def blended(self) -> float:
        """Weighted blend, renormalized over the metrics present."""
        parts: list[tuple[float, float]] = []
        if self.clip_score is not None:
            parts.append((W_CLIP, self.clip_score))
        if self.ocr_score is not None:
            parts.append((W_OCR, self.ocr_score))
        if self.judge_score is not None:
            parts.append((W_JUDGE, self.judge_score))
        if not parts:
            return 0.0
        total_w = sum(w for w, _ in parts)
        return sum(w * s for w, s in parts) / total_w


@dataclass
class Scorecard:
    provider_id: str
    scores: list[PromptScore] = field(default_factory=list)

    def by_dimension(self) -> dict[str, float]:
        dims: dict[str, list[float]] = {}
        for s in self.scores:
            dims.setdefault(s.dimension, []).append(s.blended)
        return {d: sum(v) / len(v) for d, v in dims.items()}

    @property
    def overall(self) -> float:
        per_dim = self.by_dimension()
        if not per_dim:
            return 0.0
        return sum(per_dim.values()) / len(per_dim)


def load_prompts(path: Path) -> list[BenchmarkPrompt]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [BenchmarkPrompt(**p) for p in data["prompts"]]


def ocr_match_score(extracted: str, expected: str) -> float:
    """Token-level recall of expected text in OCR output, 0-1."""
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())  # noqa: E731
    expected_tokens = norm(expected).split()
    if not expected_tokens:
        return 0.0
    found = norm(extracted).split()
    hits = sum(1 for t in expected_tokens if t in found)
    return hits / len(expected_tokens)


async def judge_frames(
    llm: LLMPort, prompt: str, frame_descriptions: list[str],
) -> float | None:
    """LLM-judge over frame descriptions. Returns 0-1 or None on parse failure."""
    raw = await llm.complete(
        _JUDGE_PROMPT.format(prompt=prompt, frames="\n".join(frame_descriptions)),
        temperature=0.2,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```"))
    try:
        data = json.loads(raw)
        vals = [float(data[k]) for k in ("adherence", "artifacts", "coherence")]
        return max(0.0, min(1.0, sum(vals) / (3 * 10)))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.warning("benchmark.judge.parse_failed", raw=raw[:200])
        return None


class BenchmarkProviderUseCase:
    """Score one provider against the prompt suite.

    The actual clip generation + frame extraction is injected as callables so
    the harness logic stays testable without providers or ffmpeg.
    """

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def score_prompt(
        self,
        bp: BenchmarkPrompt,
        *,
        frame_descriptions: list[str],
        clip_score: float | None = None,
        ocr_text: str | None = None,
    ) -> PromptScore:
        score = PromptScore(prompt_id=bp.id, dimension=bp.dimension, clip_score=clip_score)
        if bp.expected_text and ocr_text is not None:
            score.ocr_score = ocr_match_score(ocr_text, bp.expected_text)
        score.judge_score = await judge_frames(self._llm, bp.prompt, frame_descriptions)
        return score


__all__ = [
    "BenchmarkPrompt",
    "BenchmarkProviderUseCase",
    "PromptScore",
    "Scorecard",
    "judge_frames",
    "load_prompts",
    "ocr_match_score",
]
