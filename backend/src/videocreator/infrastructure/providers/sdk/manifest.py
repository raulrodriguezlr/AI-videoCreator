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
    #: Credit-billed providers (e.g. Higgsfield) price per generation in credits
    #: rather than per second. 0 = not credit-billed. The UI converts this to an
    #: approximate $ via `settings.higgsfield_usd_per_credit`.
    credits: float = 0.0


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
    #: True when the plan includes this model at no per-clip credit cost
    #: (e.g. Higgsfield "365-day unlimited" image models) — the advisor
    #: surfaces these first for high-volume work.
    unlimited: bool = False
    #: True when the model enforces strict identity/IP filters and will refuse
    #: real named people or copyrighted characters (Veo, Sora). The copyright
    #: guard drops these when a script references real people.
    copyright_strict: bool = False
    #: Content kinds this model is a good fit for, e.g.
    #: ["animation_3d", "animation_2d", "talking_head"]. Drives recommendations.
    good_for: list[str] = Field(default_factory=list)
    #: Provider-native submit path / model identifier. For Higgsfield this is the
    #: namespaced model id used as the POST path (e.g. "higgsfield-ai/dop/standard"
    #: on the official API, or "wan2-6" on the web backend). Empty → use `id`.
    endpoint: str = ""
    #: Which backend serves this model: "api" = official/stable, anything else
    #: (e.g. "web") = experimental/undocumented. Surfaced to the UI as a warning.
    backend: str = "api"
    #: Higgsfield CLI `job_set_type` (e.g. "text2image_soul_v2", "kling3_0").
    #: When set, the adapter drives generation through the official `hf` CLI
    #: (OAuth session → spends the user's PLUS subscription credits) instead of
    #: the REST API. This is the working path; `endpoint`/`backend` are legacy.
    cli_type: str = ""


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
