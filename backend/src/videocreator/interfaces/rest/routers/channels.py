"""Channels Hub endpoints — connect/list/disconnect accounts + enqueue uploads.

The whole router is gated behind the ``channels_feature_enabled`` runtime flag
(off by default); when off every route returns 403 so the feature is invisible
unless the user opts in from Settings.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from videocreator.domain.value_objects import PublishPlatform
from videocreator.interfaces.rest.deps import ContainerDep, UserIdDep
from videocreator.shared.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/channels", tags=["channels"])


def _ensure_enabled(container: ContainerDep) -> None:
    rc = container.runtime_config().get()
    if not bool(rc.get("channels_feature_enabled", False)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Channels feature is disabled")


# ---- schemas ---------------------------------------------------------------
class AccountResponse(BaseModel):
    id: str
    platform: str
    display_name: str
    handle: str | None = None
    status: str


class ConnectRequest(BaseModel):
    client_id: str
    client_secret: str


class UploadRequest(BaseModel):
    source: str  # episode | short
    source_id: str
    account_ids: list[str]
    metadata: dict[str, Any] = {}
    scheduled_at: datetime | None = None


class PublishJobResponse(BaseModel):
    id: str
    account_id: str
    platform: str
    source: str
    source_id: str
    status: str
    result_url: str | None = None
    error: str | None = None
    scheduled_at: datetime | None = None


def _account_dto(acc: Any) -> AccountResponse:
    return AccountResponse(
        id=str(acc.id), platform=acc.platform.value, display_name=acc.display_name,
        handle=acc.handle, status=acc.status.value,
    )


def _job_dto(job: Any) -> PublishJobResponse:
    return PublishJobResponse(
        id=str(job.id), account_id=str(job.account_id), platform=job.platform.value,
        source=job.source, source_id=job.source_id, status=job.status.value,
        result_url=job.result_url, error=job.error, scheduled_at=job.scheduled_at,
    )


# ---- accounts --------------------------------------------------------------
@router.get("", response_model=list[AccountResponse], summary="List connected accounts")
async def list_accounts(container: ContainerDep, user_id: UserIdDep) -> list[AccountResponse]:
    _ensure_enabled(container)
    accounts = await container.oauth_account_service().list_accounts(user_id)
    return [_account_dto(a) for a in accounts]


@router.post("/{platform}/connect", response_model=AccountResponse, summary="Connect an account (browser OAuth)")
async def connect_account(
    platform: str, body: ConnectRequest, container: ContainerDep, user_id: UserIdDep,
) -> AccountResponse:
    _ensure_enabled(container)
    try:
        plat = PublishPlatform(platform)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown platform {platform}")
    account = await container.oauth_account_service().connect(
        user_id, plat, client_id=body.client_id, client_secret=body.client_secret,
    )
    return _account_dto(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect an account")
async def disconnect_account(account_id: str, container: ContainerDep, user_id: UserIdDep) -> None:
    _ensure_enabled(container)
    repo = container.publish_account_repo()
    account = await repo.get(account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    await container.oauth_account_service().disconnect(account)


@router.post(
    "/{account_id}/verify", response_model=AccountResponse,
    summary="Health-check an account with a minimal per-platform auth call",
)
async def verify_account(account_id: str, container: ContainerDep, user_id: UserIdDep) -> AccountResponse:
    _ensure_enabled(container)
    repo = container.publish_account_repo()
    account = await repo.get(account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    verified = await container.oauth_account_service().verify(account)
    return _account_dto(verified)


# ---- uploads ---------------------------------------------------------------
@router.post("/upload", response_model=list[PublishJobResponse], summary="Enqueue an upload (batch + schedule)")
async def enqueue_upload(
    body: UploadRequest, container: ContainerDep, user_id: UserIdDep,
) -> list[PublishJobResponse]:
    _ensure_enabled(container)
    try:
        jobs = await container.publish_service().enqueue(
            user_id=user_id, account_ids=body.account_ids, source=body.source,
            source_id=body.source_id, metadata=body.metadata, scheduled_at=body.scheduled_at,
        )
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return [_job_dto(j) for j in jobs]


@router.get("/uploads", response_model=list[PublishJobResponse], summary="Upload history + status")
async def list_uploads(container: ContainerDep, user_id: UserIdDep) -> list[PublishJobResponse]:
    _ensure_enabled(container)
    jobs = await container.publish_job_repo().list_for_user(user_id)
    return [_job_dto(j) for j in jobs]


__all__ = ["router"]
