"""Domain and application error hierarchy.

Errors map cleanly to HTTP Problem Details (RFC 7807) at the interface layer.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base for all errors raised by domain or application layers."""

    http_status: int = 500
    error_code: str = "domain_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    http_status = 404
    error_code = "not_found"


class ConflictError(DomainError):
    http_status = 409
    error_code = "conflict"


class ValidationError(DomainError):
    http_status = 422
    error_code = "validation_error"


class UnauthorizedError(DomainError):
    http_status = 401
    error_code = "unauthorized"


class ForbiddenError(DomainError):
    http_status = 403
    error_code = "forbidden"


class ProviderError(DomainError):
    """Raised when an external provider fails."""

    http_status = 502
    error_code = "provider_error"


class ProviderUnavailableError(ProviderError):
    http_status = 503
    error_code = "provider_unavailable"


class RateLimitError(ProviderError):
    http_status = 429
    error_code = "rate_limited"


class BudgetExceededError(DomainError):
    http_status = 402
    error_code = "budget_exceeded"


class ProviderQuotaError(ProviderError):
    """Provider rejected the request because the account quota is exhausted."""

    http_status = 429
    error_code = "provider_quota_exceeded"


class ProviderSafetyError(ProviderError):
    """Provider refused generation on content-safety grounds."""

    http_status = 422
    error_code = "provider_safety_rejected"


class TransientProviderError(ProviderError):
    """Retryable provider failure (network blip, 5xx, rate limit)."""

    http_status = 502
    error_code = "provider_transient"


class AllProvidersFailedError(ProviderError):
    """Every provider in the fallback chain failed."""

    http_status = 502
    error_code = "all_providers_failed"


class ProviderTimeoutError(ProviderError):
    """Provider job did not complete within the allotted polling window."""

    http_status = 504
    error_code = "provider_timeout"


# --- ElevenLabs Studio specific (inherit shared semantics, distinct codes) ---
class ElevenLabsStudioQuotaError(ProviderQuotaError):
    error_code = "elevenlabs_studio_quota"


class ElevenLabsStudioSafetyError(ProviderSafetyError):
    error_code = "elevenlabs_studio_safety"


class ElevenLabsStudioTimeoutError(ProviderTimeoutError):
    error_code = "elevenlabs_studio_timeout"


# --- Artlist specific ---
class ArtlistModelUnavailableError(ProviderUnavailableError):
    error_code = "artlist_model_unavailable"


class ArtlistTimeoutError(ProviderTimeoutError):
    error_code = "artlist_timeout"


# Concrete domain errors
class PodNotFound(NotFoundError):
    error_code = "pod_not_found"


class EpisodeNotFound(NotFoundError):
    error_code = "episode_not_found"


class CharacterNotFound(NotFoundError):
    error_code = "character_not_found"


class JobNotFound(NotFoundError):
    error_code = "job_not_found"


class ScriptNotFound(NotFoundError):
    error_code = "script_not_found"


class ShortNotFound(NotFoundError):
    error_code = "short_not_found"


class SeoMetadataNotFound(NotFoundError):
    error_code = "seo_metadata_not_found"


class InvalidScript(ValidationError):
    error_code = "invalid_script"


# --- Higgsfield specific ---
class HiggsfieldNeedsAuthError(ProviderError):
    """higgsfield CLI requires auth — user must run `hf auth login`."""

    http_status = 401
    error_code = "higgsfield_needs_auth"
