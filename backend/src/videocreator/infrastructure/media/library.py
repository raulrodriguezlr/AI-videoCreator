"""Storage-backed media library.

Every episode artifact (clips, audio, frames, the final render) lives under one
place: the object store, keyed ``episodes/<episode_id>/<relpath>``. Imported
pods have their media ingested there too, so nothing is ever served from the
old `pods/` tree. The frontend only ever sees `/storage/...` URLs.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from videocreator.domain.entities import Episode
from videocreator.domain.ports import StoragePort
from videocreator.domain.value_objects import MediaAsset

_API_PREFIX = "/api/v1"
EPISODE_BUCKET = "episodes"

# Extension → (kind, mime). Lowercase, leading dot.
_VIDEO = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
          ".mkv": "video/x-matroska", ".m4v": "video/mp4"}
_IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
_AUDIO = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
          ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg"}
_SUBTITLE = {".srt": "text/plain", ".vtt": "text/vtt"}


def _classify(suffix: str) -> tuple[str, str] | None:
    s = suffix.lower()
    for kind, table in (("video", _VIDEO), ("image", _IMAGE), ("audio", _AUDIO),
                        ("subtitle", _SUBTITLE)):
        if s in table:
            return kind, table[s]
    return None


class LocalMediaLibrary:
    """`MediaLibraryPort` reading every episode artifact from the object store."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def list_for_episode(self, episode: Episode) -> list[MediaAsset]:
        prefix = f"{episode.id}/"
        keys = await self._storage.list_keys(EPISODE_BUCKET, prefix=prefix)
        assets: list[MediaAsset] = []
        for key in sorted(keys):
            rel = key[len(prefix):] if key.startswith(prefix) else key
            classified = _classify(PurePosixPath(rel).suffix)
            if classified is None:
                continue
            kind, mime = classified
            parts = PurePosixPath(rel).parts
            assets.append(MediaAsset(
                kind=kind, name=rel,
                group=parts[0] if len(parts) > 1 else None,
                url=f"{_API_PREFIX}/storage/{EPISODE_BUCKET}/{key}",
                content_type=mime,
            ))
        return assets


__all__ = ["EPISODE_BUCKET", "LocalMediaLibrary"]
