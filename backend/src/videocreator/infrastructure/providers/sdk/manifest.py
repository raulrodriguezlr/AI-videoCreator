"""Pydantic models for provider.yaml manifests.

Each provider plugin ships a `provider.yaml` that declares its identity,
capabilities, cost model, latency profile, auth requirements, and adapter type.
The registry loads and validates these at discover-time.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CostModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    per_second_usd: float = 0.0
    per_request_usd: float = 0.0
    currency: str = "USD"


class LatencyProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    p50_s: float = 30
    p95_s: float = 120
    timeout_s: float = 600


class AuthSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vault_key: str
    header: str = "Authorization"
    prefix: str = "Bearer"


class ModelSpec(BaseModel):
    """A concrete model exposed by this provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: str = "other"
    capabilities: list[str] = Field(default_factory=list)
    max_duration_s: int = 5
    max_resolution: tuple[int, int] = (1920, 1080)
    cost: CostModel = Field(default_factory=CostModel)
    latency: LatencyProfile = Field(default_factory=LatencyProfile)
    strengths: list[str] = Field(default_factory=list)


AdapterType = Literal["python", "openapi", "comfyui_workflow", "http_webhook"]


class AdapterSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: AdapterType
    entrypoint: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderManifest(BaseModel):
    """Top-level schema for provider.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    version: str = "1.0"
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
    cost: CostModel = Field(default_factory=CostModel)
    latency: LatencyProfile = Field(default_factory=LatencyProfile)
    auth: AuthSpec | None = None
    adapter: AdapterSpec
    tags: list[str] = Field(default_factory=list)


__all__ = [
    "AdapterSpec",
    "AuthSpec",
    "CostModel",
    "LatencyProfile",
    "ModelSpec",
    "ProviderManifest",
]
