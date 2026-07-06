"""Local gameplay b-roll library for the shorts "split" layout.

Unlike `cc0_library.CC0BrollLibrary` (which fetches licence-cleared "satisfying"
footage from Pexels/Pixabay at render time), this library indexes mp4s the user
drops into a local folder — `backend/var/broll/gameplay/` by default — such as
Minecraft parkour, GTA driving, subway-surfer-style gameplay, etc. Those clips
are the user's own responsibility to source legally; this library only indexes
and rotates them, it does not fetch or vet licences.

Two responsibilities:

1. **Indexing** — list the mp4s in the folder, probing each one's duration via
   `ffprobe` (cached by mtime+size so repeat calls are free).
2. **Rotation** — round-robin across the indexed clips so consecutive shorts
   don't reuse the same clip back-to-back. The "last used index" is persisted
   to a small JSON file in the same folder, so rotation survives process
   restarts.

`fetch(query, max_duration_s=...)` mirrors `CC0BrollLibrary.fetch`'s signature
(the query is accepted but ignored — local clips aren't tagged/searchable) so
`ShortRenderHandler._fetch_broll` can use either library interchangeably.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.infrastructure.media.cc0_library import AssetLicense, MediaAsset
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")
_STATE_FILENAME = ".rotation_state.json"
_DURATION_CACHE_FILENAME = ".duration_cache.json"


@dataclass(frozen=True)
class GameplayClip:
    """One indexed local gameplay clip."""

    path: Path
    duration_s: float
    attribution: dict[str, str] | None = None

    @property
    def name(self) -> str:
        return self.path.name


def probe_duration_s(path: Path) -> float:
    """Duration in seconds via `ffprobe`, or `0.0` on any failure."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(path),
            ],
            stderr=subprocess.DEVNULL,
        )
        return float(out.strip() or 0.0)
    except Exception as exc:  # noqa: BLE001 — best-effort probing
        log.warning("gameplay_broll.probe_failed", path=str(path), error=str(exc))
        return 0.0


class GameplayBrollLibrary:
    """Indexes + round-robin rotates local gameplay mp4s for the split layout."""

    def __init__(self, folder: Path) -> None:
        self._dir = folder

    @property
    def folder(self) -> Path:
        return self._dir

    # ---- indexing -----------------------------------------------------------
    def _duration_cache_path(self) -> Path:
        return self._dir / _DURATION_CACHE_FILENAME

    def _load_duration_cache(self) -> dict[str, Any]:
        p = self._duration_cache_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_duration_cache(self, cache: dict[str, Any]) -> None:
        try:
            self._duration_cache_path().write_text(
                json.dumps(cache, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — cache is best-effort
            log.warning("gameplay_broll.cache_write_failed", error=str(exc))

    def _attribution_for(self, clip_path: Path) -> dict[str, str] | None:
        side = clip_path.with_suffix(clip_path.suffix + ".attribution.json")
        if not side.exists():
            return None
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def list_clips(self) -> list[GameplayClip]:
        """List indexed clips, probing (and caching) each one's duration.

        Cache key is `<name>:<mtime>:<size>` so an edited/replaced file is
        re-probed automatically while an untouched one is free.
        """
        if not self._dir.is_dir():
            return []
        cache = self._load_duration_cache()
        dirty = False
        clips: list[GameplayClip] = []
        for path in sorted(self._dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _VIDEO_EXTS:
                continue
            stat = path.stat()
            cache_key = f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}"
            entry = cache.get(path.name)
            if entry and entry.get("key") == cache_key:
                duration = float(entry.get("duration_s") or 0.0)
            else:
                duration = probe_duration_s(path)
                cache[path.name] = {"key": cache_key, "duration_s": duration}
                dirty = True
            clips.append(GameplayClip(
                path=path, duration_s=duration,
                attribution=self._attribution_for(path),
            ))
        if dirty:
            self._save_duration_cache(cache)
        return clips

    @property
    def is_empty(self) -> bool:
        return not self.list_clips()

    # ---- rotation -------------------------------------------------------------
    def _state_path(self) -> Path:
        return self._dir / _STATE_FILENAME

    def _load_last_index(self) -> int:
        p = self._state_path()
        if not p.exists():
            return -1
        try:
            return int(json.loads(p.read_text(encoding="utf-8")).get("last_index", -1))
        except Exception:  # noqa: BLE001
            return -1

    def _save_last_index(self, index: int) -> None:
        try:
            self._state_path().write_text(
                json.dumps({"last_index": index}), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — rotation state is best-effort
            log.warning("gameplay_broll.state_write_failed", error=str(exc))

    def next_clip(self) -> GameplayClip | None:
        """Round-robin the next clip, persisting the new position.

        Returns `None` when the folder has no indexed clips.
        """
        clips = self.list_clips()
        if not clips:
            return None
        last = self._load_last_index()
        index = (last + 1) % len(clips)
        self._save_last_index(index)
        return clips[index]

    # ---- CC0BrollLibrary-compatible interface --------------------------------
    async def fetch(self, query: str, *, max_duration_s: float = 0.0) -> MediaAsset | None:
        """Round-robin the next local clip as a `MediaAsset`, or `None` if empty.

        Signature-compatible with `CC0BrollLibrary.fetch` so `ShortRenderHandler`
        can use either interchangeably; `query`/`max_duration_s` are accepted but
        unused (local clips aren't searchable/trimmed by duration here).
        """
        clip = self.next_clip()
        if clip is None:
            return None
        attribution = clip.attribution or {}
        return MediaAsset(
            path=clip.path,
            kind="video",
            license=AssetLicense(
                source=str(attribution.get("source") or "local"),
                license=str(attribution.get("license") or "user-provided"),
                source_url=str(attribution.get("source_url") or ""),
                author=str(attribution.get("author") or ""),
            ),
            tags=(query,),
            duration_s=clip.duration_s,
        )


# ---------------------------------------------------------------------------
# Composite: local gameplay clips first, remote CC0 catalog as fallback
# ---------------------------------------------------------------------------
class CompositeBrollLibrary:
    """`split` layout b-roll source: the user's local gameplay folder first,
    the remote CC0 (Pexels/Pixabay) catalog as a fallback when it's empty.

    Keeps the existing `CC0BrollLibrary` behaviour fully intact for users who
    haven't dropped any local clips in yet, while giving priority to
    Minecraft-parkour/GTA-style local footage once it's there.
    """

    def __init__(self, gameplay: GameplayBrollLibrary, remote: Any) -> None:
        self._gameplay = gameplay
        self._remote = remote

    @property
    def gameplay(self) -> GameplayBrollLibrary:
        return self._gameplay

    async def fetch(self, query: str, *, max_duration_s: float = 0.0) -> MediaAsset | None:
        if not self._gameplay.is_empty:
            asset = await self._gameplay.fetch(query, max_duration_s=max_duration_s)
            if asset is not None:
                return asset
        if self._remote is not None:
            return await self._remote.fetch(query, max_duration_s=max_duration_s)
        return None


# ---------------------------------------------------------------------------
# Populate from Pexels — a handful of free vertical gameplay/satisfying clips
# ---------------------------------------------------------------------------
_POPULATE_QUERIES = ("satisfying", "slime", "kinetic sand", "soap cutting", "parkour")


@dataclass(frozen=True)
class PopulatedClip:
    filename: str
    query: str
    author: str
    source_url: str


async def populate_from_pexels(
    folder: Path, *, api_key: str, count: int = 5, http_client: Any = None,
) -> list[PopulatedClip]:
    """Download `count` free vertical clips from Pexels into `folder`.

    Each clip gets a `<file>.attribution.json` sidecar (author + source URL)
    so the UI/credits pipeline can show provenance. `http_client` is an
    optional pre-built `httpx.AsyncClient`-like object, injected so tests never
    hit the network. Raises `ValueError` if `api_key` is empty — the caller
    (REST layer) turns that into a 422 with sign-up instructions.
    """
    if not api_key:
        raise ValueError("PEXELS_API_KEY is required to populate b-roll")

    import httpx  # noqa: PLC0415 — optional/heavy

    folder.mkdir(parents=True, exist_ok=True)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    downloaded: list[PopulatedClip] = []
    try:
        queries = list(_POPULATE_QUERIES)[:max(1, min(count, len(_POPULATE_QUERIES)))]
        for query in queries:
            if len(downloaded) >= count:
                break
            try:
                r = await client.get(
                    "https://api.pexels.com/videos/search",
                    params={"query": query, "per_page": "1", "orientation": "portrait"},
                    headers={"Authorization": api_key},
                )
                r.raise_for_status()
                data = r.json()
            except Exception as exc:  # noqa: BLE001 — best-effort, skip this query
                log.warning("gameplay_broll.populate_search_failed", query=query, error=str(exc))
                continue

            videos = data.get("videos") or []
            if not videos:
                continue
            video = videos[0]
            files = sorted(
                (f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"),
                key=lambda f: (f.get("height") or 0),
                reverse=True,
            )
            if not files:
                continue
            file_url = str(files[0].get("link") or "")
            if not file_url:
                continue

            safe_query = "".join(ch if ch.isalnum() else "_" for ch in query)[:30]
            # Sanitize the API-provided id too — a hostile/altered response must
            # not be able to path-traverse out of the b-roll folder.
            safe_id = "".join(ch if ch.isalnum() else "_" for ch in str(video.get("id", "x")))[:20]
            filename = f"pexels_{safe_query}_{safe_id}.mp4"
            dest = folder / filename
            try:
                dr = await client.get(file_url)
                dr.raise_for_status()
                dest.write_bytes(dr.content)
            except Exception as exc:  # noqa: BLE001 — best-effort, skip this clip
                log.warning("gameplay_broll.populate_download_failed", query=query, error=str(exc))
                continue

            author = str((video.get("user") or {}).get("name") or "")
            source_url = str(video.get("url") or "")
            side = dest.with_suffix(dest.suffix + ".attribution.json")
            side.write_text(
                json.dumps({
                    "source": "pexels",
                    "license": "Pexels License (https://www.pexels.com/license/)",
                    "source_url": source_url,
                    "author": author,
                }, indent=2),
                encoding="utf-8",
            )
            downloaded.append(PopulatedClip(
                filename=filename, query=query, author=author, source_url=source_url,
            ))
    finally:
        if owns_client:
            await client.aclose()
    return downloaded


__all__ = [
    "GameplayBrollLibrary",
    "GameplayClip",
    "CompositeBrollLibrary",
    "PopulatedClip",
    "populate_from_pexels",
    "probe_duration_s",
]
