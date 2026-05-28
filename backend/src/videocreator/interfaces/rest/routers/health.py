"""Health & readiness endpoints."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import APIRouter

from videocreator.interfaces.rest.deps import ContainerDep, SettingsDep
from videocreator.interfaces.rest.schemas import HealthResponse

router = APIRouter(tags=["health"])


def _package_version() -> str:
    try:
        return _pkg_version("videocreator")
    except PackageNotFoundError:
        return "0.0.0+unknown"


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health(settings: SettingsDep, container: ContainerDep) -> HealthResponse:
    components: dict[str, str] = {
        "database": "configured",
        "storage": "configured",
        "queue": settings.queue_backend,
        "llm": "gemini" if settings.google_api_key else "missing_api_key",
    }
    # Touch the storage so a misconfigured volume surfaces here, not on first upload.
    try:
        container.storage()
    except Exception as exc:  # noqa: BLE001
        components["storage"] = f"error: {exc}"

    return HealthResponse(
        status="ok",
        app_mode=settings.app_mode,
        version=_package_version(),
        components=components,
    )


__all__ = ["router"]
