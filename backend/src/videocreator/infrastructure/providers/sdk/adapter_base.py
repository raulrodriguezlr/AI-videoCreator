"""Abstract base for SDK-managed provider adapters.

Concrete adapters (python, openapi, comfyui, webhook) subclass this and
implement `generate()` and optionally `health()` / `estimate_cost()`.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest


@dataclass(frozen=True)
class GenRequest:
    """Unified generation request passed to every adapter."""

    prompt: str
    duration_s: float = 5.0
    width: int = 1080
    height: int = 1920
    seed: int | None = None
    negative_prompt: str | None = None
    model_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenResult:
    """Unified generation result returned by adapters."""

    video_bytes: bytes
    duration_s: float
    width: int
    height: int
    model_id: str | None = None
    seed: int | None = None
    has_audio: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class AdapterBase(abc.ABC):
    """ABC for all provider SDK adapters."""

    def __init__(
        self,
        manifest: ProviderManifest,
        base_dir: Path,
        *,
        vault: Any = None,
    ) -> None:
        self.manifest = manifest
        self.base_dir = base_dir
        self._vault = vault

    @property
    def provider_id(self) -> str:
        return self.manifest.id

    @abc.abstractmethod
    async def generate(self, request: GenRequest) -> GenResult:
        """Execute a generation request. Must be implemented by subclasses."""

    async def health(self) -> dict[str, Any]:
        """Check provider health. Override for custom checks."""
        return {"available": True, "name": self.manifest.name}

    def estimate_cost(self, duration_s: float) -> float:
        """Estimate cost for a generation of given duration."""
        c = self.manifest.cost
        return c.per_request_usd + c.per_second_usd * duration_s

    async def aclose(self) -> None:
        """Cleanup resources. Override if adapter holds connections."""


__all__ = ["AdapterBase", "GenRequest", "GenResult"]
