"""Living library of viral formats — genome clustering + lifecycle (§12.4/§16.13).

Each analyzed video deposits its genome; similar genomes cluster into a
"format" (vector similarity >= 0.88 → same format_id, sighting counter++).
Lifecycle: adoption curve = sightings/day; no sightings for 14 days → BURNED
→ vetoed in suggestions (arriving late to a meme is worse than not arriving).

Embeddings are injected as vectors (caller encodes `why_it_works` + structure)
so this module stays free of sentence-transformers; persistence is JSON +
the pluggable EmbeddingIndex backend (FAISS or numpy) — local-first.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from videocreator.domain.value_objects import ViralGenome
from videocreator.infrastructure.vector.embedding_index import _make_backend
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: §16.13: neighbor with score > 0.88 → same format.
CLUSTER_THRESHOLD = 0.88
#: §12.4: no sightings for 14 days → burned.
BURN_AFTER_S = 14 * 24 * 3600

FormatStatus = str  # "emerging" | "peak" | "burned"


@dataclass
class FormatRecord:
    format_id: str
    sightings: list[float] = field(default_factory=list)  # unix timestamps
    niches: list[str] = field(default_factory=list)
    sample_genome: dict[str, Any] = field(default_factory=dict)

    @property
    def first_seen(self) -> float:
        return min(self.sightings) if self.sightings else 0.0

    @property
    def last_seen(self) -> float:
        return max(self.sightings) if self.sightings else 0.0

    def adoption_rate(self, *, now: float | None = None) -> float:
        """Sightings per day since first seen."""
        if not self.sightings:
            return 0.0
        now = now if now is not None else time.time()
        days = max((now - self.first_seen) / 86400.0, 1.0 / 24)
        return len(self.sightings) / days

    def status(self, *, now: float | None = None) -> FormatStatus:
        now = now if now is not None else time.time()
        if not self.sightings or now - self.last_seen > BURN_AFTER_S:
            return "burned"
        # Emerging: most sightings recent (last 3 days hold half or more).
        recent = sum(1 for t in self.sightings if now - t <= 3 * 86400)
        return "emerging" if recent * 2 >= len(self.sightings) else "peak"


class FormatLibrary:
    """Persistent genome → format clustering store."""

    def __init__(self, library_dir: Path, *, dim: int = 384) -> None:
        self._dir = library_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._meta_path = library_dir / "formats.json"
        self._index_path = library_dir / "format_index"
        self._backend = _make_backend(self._index_path, dim)
        self._records: dict[int, FormatRecord] = {}
        self._next_id = 1
        self._load_meta()

    # ---- public API --------------------------------------------------------
    def add_genome(
        self,
        genome: ViralGenome,
        vector: np.ndarray,
        *,
        niche: str | None = None,
        now: float | None = None,
    ) -> str:
        """Deposit a genome. Returns the (existing or new) format_id."""
        now = now if now is not None else time.time()
        vec = np.asarray(vector, dtype=np.float32)
        hits = self._backend.search(vec, k=5)
        if hits and hits[0][1] >= CLUSTER_THRESHOLD:
            record = self._records[hits[0][0]]
            record.sightings.append(now)
            if niche and niche not in record.niches:
                record.niches.append(niche)
            self._persist()
            log.info("format_library.sighting", format_id=record.format_id,
                     total=len(record.sightings))
            return record.format_id

        numeric_id = self._next_id
        self._next_id += 1
        format_id = genome.format_id or f"format-{numeric_id:04d}"
        record = FormatRecord(
            format_id=format_id,
            sightings=[now],
            niches=[niche] if niche else [],
            sample_genome=genome.model_dump(mode="json"),
        )
        self._records[numeric_id] = record
        self._backend.add(numeric_id, vec)
        self._backend.save(self._index_path)
        self._persist()
        log.info("format_library.new_format", format_id=format_id)
        return format_id

    def get(self, format_id: str) -> FormatRecord | None:
        for record in self._records.values():
            if record.format_id == format_id:
                return record
        return None

    def list_formats(self) -> list[FormatRecord]:
        return list(self._records.values())

    def vetoed_ids(self, *, now: float | None = None) -> set[str]:
        """Format ids currently burned — excluded from suggestions."""
        return {
            r.format_id for r in self._records.values()
            if r.status(now=now) == "burned"
        }

    def emerging(self, *, now: float | None = None) -> list[FormatRecord]:
        """Pre-peak formats — what the Daily Briefing leads with."""
        return [
            r for r in self._records.values()
            if r.status(now=now) == "emerging"
        ]

    # ---- persistence -------------------------------------------------------
    def _persist(self) -> None:
        data = {
            "next_id": self._next_id,
            "records": {
                str(nid): {
                    "format_id": r.format_id,
                    "sightings": r.sightings,
                    "niches": r.niches,
                    "sample_genome": r.sample_genome,
                }
                for nid, r in self._records.items()
            },
        }
        self._meta_path.write_text(json.dumps(data), encoding="utf-8")

    def _load_meta(self) -> None:
        if not self._meta_path.exists():
            return
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("format_library.meta_corrupt", path=str(self._meta_path))
            return
        self._next_id = int(data.get("next_id", 1))
        for nid, raw in data.get("records", {}).items():
            self._records[int(nid)] = FormatRecord(
                format_id=raw["format_id"],
                sightings=[float(t) for t in raw.get("sightings", [])],
                niches=list(raw.get("niches", [])),
                sample_genome=raw.get("sample_genome", {}),
            )


__all__ = [
    "BURN_AFTER_S",
    "CLUSTER_THRESHOLD",
    "FormatLibrary",
    "FormatRecord",
]
