"""Storage proxy — serves locally-stored artifacts under the API.

Required so the frontend can render uploaded reference images, final videos,
etc. via the same origin as the API. In server/cloud mode this is replaced by
S3/MinIO pre-signed URLs (the StoragePort.url_for adapter), so this route only
fires in local mode.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from videocreator.infrastructure.storage.file_storage import LocalFileStorage
from videocreator.interfaces.rest.deps import ContainerDep

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get(
    "/{bucket}/{key:path}",
    summary="Stream a locally-stored object",
    response_class=FileResponse,
)
async def get_object(bucket: str, key: str, container: ContainerDep) -> FileResponse:
    storage = container.storage()
    if not isinstance(storage, LocalFileStorage):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="storage proxy only available in local mode",
        )
    path = await storage.open_path(bucket, key)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="object not found")
    return FileResponse(
        path,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


__all__ = ["router"]
