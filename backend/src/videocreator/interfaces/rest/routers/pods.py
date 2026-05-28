"""Pod CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.domain.entities import PodConfig
from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CreatePodRequest,
    PodConfigPayload,
    PodResponse,
    UpdatePodConfigRequest,
)
from videocreator.shared.ids import PodId

router = APIRouter(prefix="/pods", tags=["pods"])


def _to_response(pod) -> PodResponse:  # type: ignore[no-untyped-def]
    return PodResponse(
        id=pod.id,
        owner_id=pod.owner_id,
        name=pod.name,
        config=PodConfigPayload(**pod.config.model_dump(exclude={"schema_version"})),
        created_at=pod.created_at,
        updated_at=pod.updated_at,
    )


def _to_domain_config(payload: PodConfigPayload) -> PodConfig:
    return PodConfig(**payload.model_dump())


@router.post(
    "", response_model=PodResponse, status_code=status.HTTP_201_CREATED,
    summary="Create a new pod",
)
async def create_pod(
    body: CreatePodRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> PodResponse:
    pod = await uc.pods.create.execute(
        owner_id=user_id, name=body.name, config=_to_domain_config(body.config),
    )
    return _to_response(pod)


@router.get("", response_model=list[PodResponse], summary="List my pods")
async def list_pods(uc: UseCasesDep, user_id: UserIdDep) -> list[PodResponse]:
    pods = await uc.pods.list.execute(owner_id=user_id)
    return [_to_response(p) for p in pods]


@router.get("/{pod_id}", response_model=PodResponse, summary="Get a pod by id")
async def get_pod(pod_id: str, uc: UseCasesDep, user_id: UserIdDep) -> PodResponse:
    pod = await uc.pods.get.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return _to_response(pod)


@router.put("/{pod_id}/config", response_model=PodResponse, summary="Update pod config")
async def update_pod_config(
    pod_id: str, body: UpdatePodConfigRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> PodResponse:
    pod = await uc.pods.update_config.execute(
        pod_id=PodId(pod_id), requester_id=user_id,
        config=_to_domain_config(body.config),
    )
    return _to_response(pod)


@router.delete("/{pod_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a pod")
async def delete_pod(pod_id: str, uc: UseCasesDep, user_id: UserIdDep) -> None:
    await uc.pods.delete.execute(pod_id=PodId(pod_id), requester_id=user_id)


__all__ = ["router"]
