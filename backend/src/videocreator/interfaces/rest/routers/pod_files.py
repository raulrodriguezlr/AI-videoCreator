"""Raw pod JSON file endpoints (config.json, prompts.json, …).

Faithful to the on-disk pod format: a pod's editable JSON is exposed as raw
text the UI can view and edit. Ownership is enforced via the pod use case;
filename whitelisting + JSON validation live in `PodFileStore`.
"""
from __future__ import annotations

from fastapi import APIRouter

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    PodFileContentResponse,
    PodFileListResponse,
    WritePodFileRequest,
)
from videocreator.shared.ids import PodId

router = APIRouter(prefix="/pods/{pod_id}/files", tags=["files"])


@router.get("", response_model=PodFileListResponse, summary="List editable JSON files")
async def list_files(
    pod_id: str, uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> PodFileListResponse:
    pod = await uc.pods.get.execute(pod_id=PodId(pod_id), requester_id=user_id)
    files = container.pod_file_store().list_pod_files(pod.name)
    return PodFileListResponse(files=files)


@router.get("/{name}", response_model=PodFileContentResponse, summary="Read a raw JSON file")
async def read_file(
    pod_id: str, name: str, uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> PodFileContentResponse:
    pod = await uc.pods.get.execute(pod_id=PodId(pod_id), requester_id=user_id)
    content = container.pod_file_store().read_pod_file(pod.name, name)
    return PodFileContentResponse(name=name, content=content)


@router.put("/{name}", response_model=PodFileContentResponse, summary="Overwrite a JSON file")
async def write_file(
    pod_id: str, name: str, body: WritePodFileRequest,
    uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> PodFileContentResponse:
    pod = await uc.pods.get.execute(pod_id=PodId(pod_id), requester_id=user_id)
    store = container.pod_file_store()
    store.write_pod_file(pod.name, name, body.content)
    return PodFileContentResponse(name=name, content=store.read_pod_file(pod.name, name))


__all__ = ["router"]
