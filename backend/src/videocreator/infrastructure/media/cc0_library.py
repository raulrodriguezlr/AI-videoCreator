"""CC0 / royalty-free media library for the shorts engine.

Fetches **legally redistributable** background footage (the "satisfying" b-roll
that sits under the talking video in a split-screen short) from Pexels and
Pixabay, and resolves royalty-free background music from a local catalog. Every
asset carries explicit licence metadata, persisted as a ``<file>.license.json``
sidecar; an asset whose licence cannot be established is **discarded** rather
than used (hard-fail), so nothing copyrighted ever leaks into a render.

This is deliberately NOT a path for ripped game footage (Subway Surfers, etc.):
that material is copyrighted and has no redistribution licence, so it has no
place here. Only sources whose terms permit use inside a derived video are
ingested.

Everything is best-effort: missing API keys, network errors or an empty result
return ``None`` so a render degrades to no-b-roll / no-music instead of failing.
"""
from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

AssetKind = Literal["video", "audio"]

# Licence strings for the supported sources. Both permit use and modification
# inside a derived work and redistribution as part of it; attribution is not
# legally required but we record the author regardless.
_PEXELS_LICENSE = "Pexels License (https://www.pexels.com/license/)"
_PIXABAY_LICENSE = "Pixabay Content License (https://pixabay.com/service/license-summary/)"

_HTTP_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class AssetLicense:
    """Provenance + licence of one media asset — enough to prove it's usable."""

    source: str          # "pexels" | "pixabay" | "local"
    license: str         # human-readable licence name + URL
    source_url: str = ""  # page the asset came from
    author: str = ""

    @property
    def is_known(self) -> bool:
        return bool(self.source and self.license)


@dataclass(frozen=True)
class MediaAsset:
    """A downloaded, licence-cleared media file ready to feed FFmpeg."""

    path: Path
    kind: AssetKind
    license: AssetLicense
    tags: tuple[str, ...] = ()
    duration_s: float = 0.0


def _write_license_sidecar(media_path: Path, lic: AssetLicense) -> None:
    """Persist licence metadata next to the file for provenance/audit."""
    side = media_path.with_suffix(media_path.suffix + ".license.json")
    side.write_text(json.dumps(asdict(lic), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Remote providers (b-roll video)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Candidate:
    url: str
    duration_s: float
    width: int
    height: int
    license: AssetLicense
    ext: str = "mp4"


class PexelsClient:
    """Search Pexels' free stock-video catalog (vertical-first)."""

    _ENDPOINT = "https://api.pexels.com/videos/search"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def search_videos(
        self, query: str, *, max_duration_s: float = 0.0, limit: int = 15
    ) -> list[_Candidate]:
        if not self._key:
            return []
        import httpx

        params = {
            "query": query,
            "per_page": str(limit),
            "orientation": "portrait",
        }
        headers = {"Authorization": self._key}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as c:
                r = await c.get(self._ENDPOINT, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("cc0.pexels.search_failed", query=query, error=str(exc))
            return []

        out: list[_Candidate] = []
        for v in data.get("videos", []):
            dur = float(v.get("duration") or 0.0)
            if max_duration_s and dur and dur > max_duration_s * 3:
                continue  # absurdly long source; skip
            files = sorted(
                (f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"),
                key=lambda f: (f.get("height") or 0),
                reverse=True,
            )
            if not files:
                continue
            f = files[0]
            out.append(_Candidate(
                url=str(f.get("link")),
                duration_s=dur,
                width=int(f.get("width") or 0),
                height=int(f.get("height") or 0),
                license=AssetLicense(
                    source="pexels",
                    license=_PEXELS_LICENSE,
                    source_url=str(v.get("url") or ""),
                    author=str((v.get("user") or {}).get("name") or ""),
                ),
            ))
        return out


class PixabayClient:
    """Search Pixabay's free stock-video catalog."""

    _ENDPOINT = "https://pixabay.com/api/videos/"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def search_videos(
        self, query: str, *, max_duration_s: float = 0.0, limit: int = 15
    ) -> list[_Candidate]:
        if not self._key:
            return []
        import httpx

        params = {"key": self._key, "q": query, "per_page": str(max(3, limit))}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as c:
                r = await c.get(self._ENDPOINT, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            log.warning("cc0.pixabay.search_failed", query=query, error=str(exc))
            return []

        out: list[_Candidate] = []
        for h in data.get("hits", []):
            dur = float(h.get("duration") or 0.0)
            if max_duration_s and dur and dur > max_duration_s * 3:
                continue
            streams = h.get("videos") or {}
            stream = streams.get("large") or streams.get("medium") or {}
            url = stream.get("url")
            if not url:
                continue
            out.append(_Candidate(
                url=str(url),
                duration_s=dur,
                width=int(stream.get("width") or 0),
                height=int(stream.get("height") or 0),
                license=AssetLicense(
                    source="pixabay",
                    license=_PIXABAY_LICENSE,
                    source_url=str(h.get("pageURL") or ""),
                    author=str(h.get("user") or ""),
                ),
            ))
        return out


# ---------------------------------------------------------------------------
# B-roll library (remote, license-tracked, cached)
# ---------------------------------------------------------------------------
class CC0BrollLibrary:
    """Fetch licence-cleared b-roll footage, cached locally with a sidecar."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        pexels_key: str = "",
        pixabay_key: str = "",
    ) -> None:
        self._dir = cache_dir
        self._pexels = PexelsClient(pexels_key)
        self._pixabay = PixabayClient(pixabay_key)

    @property
    def enabled(self) -> bool:
        return bool(self._pexels._key or self._pixabay._key)

    async def fetch(self, query: str, *, max_duration_s: float = 0.0) -> MediaAsset | None:
        """Return a downloaded, licence-cleared b-roll clip for ``query``.

        Searches Pexels then Pixabay, downloads the first candidate with a known
        licence, and writes a ``.license.json`` sidecar. Returns ``None`` on no
        result / no usable licence / any error.
        """
        if not self.enabled:
            return None
        candidates: list[_Candidate] = []
        for client in (self._pexels, self._pixabay):
            try:
                candidates = await client.search_videos(query, max_duration_s=max_duration_s)
            except Exception as exc:
                log.warning("cc0.broll.search_error", query=query, error=str(exc))
                candidates = []
            if candidates:
                break
        if not candidates:
            return None

        for cand in candidates:
            if not cand.license.is_known:
                continue  # hard-fail: never use an asset without a known licence
            asset = await self._download(query, cand)
            if asset is not None:
                return asset
        return None

    async def _download(self, query: str, cand: _Candidate) -> MediaAsset | None:
        import httpx

        self._dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() else "_" for ch in query)[:40]
        name = f"{cand.license.source}_{safe}_{abs(hash(cand.url)) % 10**8}.{cand.ext}"
        dest = self._dir / name
        if not dest.exists():
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S, follow_redirects=True) as c:
                    r = await c.get(cand.url)
                    r.raise_for_status()
                    await asyncio.to_thread(dest.write_bytes, r.content)
            except Exception as exc:
                log.warning("cc0.broll.download_failed", url=cand.url, error=str(exc))
                return None
        _write_license_sidecar(dest, cand.license)
        log.info("cc0.broll.ready", query=query, source=cand.license.source, path=str(dest))
        return MediaAsset(
            path=dest, kind="video", license=cand.license,
            tags=(query,), duration_s=cand.duration_s,
        )


# ---------------------------------------------------------------------------
# Music library (local catalog of royalty-free tracks)
# ---------------------------------------------------------------------------
class MusicLibrary:
    """Resolve a vibe to a local royalty-free music track.

    Catalog lives at ``backend/assets/music/catalog.json`` (vibe → list of audio
    filenames). Each track must have a ``<file>.license.json`` sidecar declaring
    a known licence; tracks without one are skipped so only cleared music plays.
    """

    def __init__(self, catalog_path: Path | None = None) -> None:
        path = catalog_path or (
            Path(__file__).resolve().parents[4] / "assets" / "music" / "catalog.json"
        )
        self._catalog: dict[str, list[MediaAsset]] = {}
        if not path.exists():
            log.info("music.catalog.missing", path=str(path))
            return
        try:
            raw: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("music.catalog.corrupt", path=str(path), error=str(exc))
            return
        music_dir = path.parent
        for vibe, filenames in raw.items():
            if vibe.startswith("_"):
                continue
            assets: list[MediaAsset] = []
            for fn in filenames:
                fp = music_dir / fn
                lic = _load_license(fp)
                if fp.exists() and lic is not None and lic.is_known:
                    assets.append(MediaAsset(path=fp, kind="audio", license=lic, tags=(vibe,)))
                else:
                    log.warning("music.track.skipped", vibe=vibe, file=fn,
                                reason="missing_file_or_license")
            if assets:
                self._catalog[vibe] = assets

    def resolve(self, vibe: str) -> MediaAsset | None:
        candidates = self._catalog.get(vibe) or self._catalog.get("energetic")
        return random.choice(candidates) if candidates else None

    @property
    def is_empty(self) -> bool:
        return not self._catalog


def _load_license(media_path: Path) -> AssetLicense | None:
    side = media_path.with_suffix(media_path.suffix + ".license.json")
    if not side.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(side.read_text(encoding="utf-8"))
    except Exception:
        return None
    return AssetLicense(
        source=str(data.get("source") or ""),
        license=str(data.get("license") or ""),
        source_url=str(data.get("source_url") or ""),
        author=str(data.get("author") or ""),
    )


__all__ = [
    "AssetLicense",
    "CC0BrollLibrary",
    "MediaAsset",
    "MusicLibrary",
    "PexelsClient",
    "PixabayClient",
]
