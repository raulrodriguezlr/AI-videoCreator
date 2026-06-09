"""Curated catalogue of strong Ollama text models + GPU VRAM detection.

The pod wizard, script/topic generation and SEO all need a capable
instruction model with good JSON adherence and multilingual (Spanish) quality.
This module exposes a hand-picked shortlist annotated with the VRAM each needs
at its default quantization, and detects the local GPU so the UI can offer the
*best models that actually fit* this machine.

VRAM figures are conservative Q4_K_M estimates (model weights + a little KV
cache headroom); they're guidance, not hard limits.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogModel:
    name: str          # Ollama ref, e.g. "qwen2.5:14b-instruct"
    label: str         # human label
    params: str        # "14B", "8x7B MoE"…
    min_vram_gb: float  # approx VRAM needed at default quant
    notes: str
    rank: int          # lower = stronger pick for this use-case


# Ordered best-first within each size tier. Kept intentionally short (~11).
_CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel("qwen2.5:14b-instruct", "Qwen2.5 14B Instruct", "14B", 10.0,
                 "Best overall — excellent JSON + Spanish.", 1),
    CatalogModel("llama3.1:8b", "Llama 3.1 8B", "8B", 6.0,
                 "Reliable all-rounder, leaves VRAM free.", 2),
    CatalogModel("mistral-nemo:12b", "Mistral Nemo 12B", "12B", 8.0,
                 "128k context — good for long scripts.", 3),
    CatalogModel("gemma2:9b", "Gemma 2 9B", "9B", 7.0,
                 "Strong reasoning, compact.", 4),
    CatalogModel("qwen2.5:7b-instruct", "Qwen2.5 7B Instruct", "7B", 6.0,
                 "Fast, solid structured output.", 5),
    CatalogModel("deepseek-r1:14b", "DeepSeek-R1 14B", "14B", 10.0,
                 "Reasoning-tuned for tricky plots.", 6),
    CatalogModel("phi3.5:3.8b", "Phi 3.5 Mini", "3.8B", 3.0,
                 "Tiny + capable, runs almost anywhere.", 7),
    CatalogModel("llama3.2:3b", "Llama 3.2 3B", "3B", 3.0,
                 "Lightweight fallback for small GPUs.", 8),
    CatalogModel("qwen2.5:32b-instruct", "Qwen2.5 32B Instruct", "32B", 20.0,
                 "Top quality — needs a big card.", 9),
    CatalogModel("gemma2:27b", "Gemma 2 27B", "27B", 18.0,
                 "High quality, large.", 10),
    CatalogModel("mixtral:8x7b", "Mixtral 8x7B", "8x7B MoE", 28.0,
                 "Mixture-of-experts, very large.", 11),
)


def detect_vram_gb() -> float | None:
    """Total VRAM of the first NVIDIA GPU in GB, or None if undetectable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    first = next((line.strip() for line in out.splitlines() if line.strip()), "")
    try:
        return round(int(first) / 1024, 1)  # MiB → GB
    except ValueError:
        return None


def recommend(vram_gb: float | None, installed: set[str]) -> list[dict[str, object]]:
    """Annotate the catalogue with fit/installed flags, best fitting first.

    When VRAM is unknown every model is marked as fitting (`fits=True`) so the
    user can still choose; otherwise models within the budget come first.
    """
    def fits(m: CatalogModel) -> bool:
        return vram_gb is None or m.min_vram_gb <= vram_gb

    ordered = sorted(_CATALOG, key=lambda m: (not fits(m), m.rank))
    return [
        {
            "name": m.name, "label": m.label, "params": m.params,
            "min_vram_gb": m.min_vram_gb, "notes": m.notes,
            "fits": fits(m), "installed": m.name in installed,
        }
        for m in ordered
    ]


__all__ = ["CatalogModel", "detect_vram_gb", "recommend"]
