"""Semantic embedding index for asset search and reuse detection.

Designed with a pluggable backend: FAISS (fast, needs faiss-cpu) or a pure-Python
fallback using numpy cosine similarity (zero-install, slower). The backend is
selected at init based on what's importable.

Assets are indexed by their text description (visual_prompt for generated clips).
Before generating a new segment, callers can search for existing assets with
score > threshold to offer reuse.
"""
from __future__ import annotations

import abc
import json
from pathlib import Path
from typing import Any

import numpy as np

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

REUSE_THRESHOLD = 0.92


class EmbeddingBackend(abc.ABC):
    """Abstract vector index backend."""

    @abc.abstractmethod
    def add(self, asset_id: int, vector: np.ndarray) -> None: ...

    @abc.abstractmethod
    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]: ...

    @abc.abstractmethod
    def save(self, path: Path) -> None: ...

    @abc.abstractmethod
    def count(self) -> int: ...


class FaissBackend(EmbeddingBackend):
    """FAISS IndexIDMap + IndexFlatIP for cosine similarity."""

    def __init__(self, index_path: Path | None, dim: int = 384) -> None:
        import faiss  # type: ignore[import-untyped]

        self._faiss = faiss
        self._path = index_path
        if index_path and index_path.exists():
            self._index = faiss.read_index(str(index_path))
        else:
            self._index = faiss.IndexIDMap(faiss.IndexFlatIP(dim))

    def add(self, asset_id: int, vector: np.ndarray) -> None:
        v = vector.reshape(1, -1).astype(np.float32)
        ids = np.array([asset_id], dtype=np.int64)
        self._index.add_with_ids(v, ids)

    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        v = vector.reshape(1, -1).astype(np.float32)
        scores, ids = self._index.search(v, min(k, max(self.count(), 1)))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def save(self, path: Path) -> None:
        self._faiss.write_index(self._index, str(path))

    def count(self) -> int:
        return self._index.ntotal


class NumpyBackend(EmbeddingBackend):
    """Pure-numpy fallback — brute-force cosine similarity. Zero deps beyond numpy."""

    def __init__(self, index_path: Path | None, dim: int = 384) -> None:
        self._path = index_path
        self._dim = dim
        self._vectors: list[np.ndarray] = []
        self._ids: list[int] = []
        if index_path and index_path.exists():
            data = json.loads(index_path.read_text())
            self._ids = data["ids"]
            self._vectors = [np.array(v, dtype=np.float32) for v in data["vectors"]]

    def add(self, asset_id: int, vector: np.ndarray) -> None:
        self._vectors.append(vector.astype(np.float32).flatten())
        self._ids.append(asset_id)

    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        if not self._vectors:
            return []
        q = vector.astype(np.float32).flatten()
        mat = np.array(self._vectors)
        scores = mat @ q
        top_k = min(k, len(self._ids))
        indices = np.argsort(scores)[-top_k:][::-1]
        return [(self._ids[i], float(scores[i])) for i in indices]

    def save(self, path: Path) -> None:
        data = {
            "ids": self._ids,
            "vectors": [v.tolist() for v in self._vectors],
        }
        path.write_text(json.dumps(data))

    def count(self) -> int:
        return len(self._ids)


def _make_backend(index_path: Path | None, dim: int) -> EmbeddingBackend:
    try:
        return FaissBackend(index_path, dim)
    except ImportError:
        log.info("vector.backend", choice="numpy", reason="faiss-cpu not installed")
        return NumpyBackend(index_path, dim)


class EmbeddingIndex:
    """High-level semantic search index for assets.

    Embeds text via sentence-transformers (lazy-loaded), stores vectors in a
    pluggable backend (FAISS or numpy fallback).
    """

    def __init__(
        self,
        index_path: Path | None = None,
        *,
        dim: int = 384,
        model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        self._index_path = index_path
        self._dim = dim
        self._model_name = model_name
        self._model: Any = None
        self._backend = _make_backend(index_path, dim)

    def _encoder(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def add(self, asset_id: int, text: str) -> None:
        """Embed text and add to index."""
        vec = self._encoder().encode([text], normalize_embeddings=True)[0]
        self._backend.add(asset_id, vec)
        if self._index_path:
            self._backend.save(self._index_path)

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        """Search for assets similar to query. Returns (asset_id, score) pairs."""
        vec = self._encoder().encode([query], normalize_embeddings=True)[0]
        return self._backend.search(vec, k)

    def add_vector(self, asset_id: int, vector: np.ndarray) -> None:
        """Add a pre-computed vector directly (skip encoding)."""
        self._backend.add(asset_id, vector)
        if self._index_path:
            self._backend.save(self._index_path)

    def search_vector(self, vector: np.ndarray, k: int = 10) -> list[tuple[int, float]]:
        """Search with a pre-computed vector."""
        return self._backend.search(vector, k)

    @property
    def count(self) -> int:
        return self._backend.count()


__all__ = [
    "REUSE_THRESHOLD",
    "EmbeddingBackend",
    "EmbeddingIndex",
    "FaissBackend",
    "NumpyBackend",
]
