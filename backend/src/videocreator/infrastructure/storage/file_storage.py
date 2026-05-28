"""Local filesystem implementation of `StoragePort`.

Layout:
    <root>/<bucket>/<key>

Keys are stored as nested paths under the bucket. Anything starting with
"../" or absolute paths is rejected to keep the writes confined to root.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from videocreator.shared.errors import ValidationError


class LocalFileStorage:
    name = "local-file"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, bucket: str, key: str) -> Path:
        if not bucket or "/" in bucket or bucket.startswith("."):
            raise ValidationError(f"invalid bucket name: {bucket!r}")
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValidationError(f"unsafe storage key: {key!r}")
        return (self._root / bucket / key).resolve()

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        path = self._resolve(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            with path.open("wb") as fp:
                if isinstance(data, bytes):
                    fp.write(data)
                else:
                    while True:
                        chunk = data.read(64 * 1024)
                        if not chunk:
                            break
                        fp.write(chunk)

        await asyncio.to_thread(_write)
        return f"{bucket}/{key}"

    async def get(self, bucket: str, key: str) -> bytes:
        path = self._resolve(bucket, key)
        return await asyncio.to_thread(path.read_bytes)

    async def open_path(self, bucket: str, key: str) -> Path:
        return self._resolve(bucket, key)

    async def delete(self, bucket: str, key: str) -> None:
        path = self._resolve(bucket, key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        # In local mode we serve files via the REST API at /api/v1/storage/...
        return f"/api/v1/storage/{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        base = (self._root / bucket).resolve()
        if not base.exists():
            return []
        prefix_path = (base / prefix).resolve() if prefix else base
        keys: list[str] = []
        for p in prefix_path.rglob("*"):
            if p.is_file():
                keys.append(str(p.relative_to(base)).replace("\\", "/"))
        return keys

    def stream(self, bucket: str, key: str) -> BinaryIO:
        """Synchronous open returning a file object (used by FastAPI StreamingResponse)."""
        path = self._resolve(bucket, key)
        return path.open("rb")  # noqa: SIM115 — caller owns lifecycle


__all__ = ["LocalFileStorage"]


# Convenience: helper for callers that need a bytes-like wrapper
def to_binary(data: bytes) -> BinaryIO:
    return BytesIO(data)
