"""Tests for EmbeddingIndex — numpy fallback backend (no sentence-transformers needed)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from videocreator.infrastructure.vector.embedding_index import (
    NumpyBackend,
    EmbeddingIndex,
)


class TestNumpyBackend:
    def test_add_and_search(self) -> None:
        backend = NumpyBackend(index_path=None, dim=4)
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        backend.add(1, v1)
        backend.add(2, v2)
        results = backend.search(v1, k=2)
        assert results[0][0] == 1
        assert results[0][1] > results[1][1]

    def test_search_empty(self) -> None:
        backend = NumpyBackend(index_path=None, dim=4)
        results = backend.search(np.ones(4, dtype=np.float32), k=5)
        assert results == []

    def test_count(self) -> None:
        backend = NumpyBackend(index_path=None, dim=4)
        assert backend.count() == 0
        backend.add(1, np.ones(4, dtype=np.float32))
        assert backend.count() == 1

    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "index.json"
        backend = NumpyBackend(index_path=None, dim=4)
        backend.add(42, np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32))
        backend.save(path)

        loaded = NumpyBackend(index_path=path, dim=4)
        assert loaded.count() == 1
        results = loaded.search(np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32), k=1)
        assert results[0][0] == 42


class TestEmbeddingIndex:
    def test_add_vector_and_search_vector(self) -> None:
        idx = EmbeddingIndex(index_path=None, dim=4)
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
        v3 = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
        idx.add_vector(1, v1)
        idx.add_vector(2, v2)
        idx.add_vector(3, v3)

        results = idx.search_vector(v1, k=2)
        assert len(results) == 2
        assert results[0][0] in (1, 2)

    def test_count(self) -> None:
        idx = EmbeddingIndex(index_path=None, dim=4)
        assert idx.count == 0
        idx.add_vector(1, np.ones(4, dtype=np.float32))
        assert idx.count == 1

    def test_k_larger_than_index(self) -> None:
        idx = EmbeddingIndex(index_path=None, dim=4)
        idx.add_vector(1, np.ones(4, dtype=np.float32))
        results = idx.search_vector(np.ones(4, dtype=np.float32), k=100)
        assert len(results) == 1

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "test_index.json"
        idx = EmbeddingIndex(index_path=path, dim=4)
        idx.add_vector(10, np.array([1, 0, 0, 0], dtype=np.float32))
        assert path.exists()

        idx2 = EmbeddingIndex(index_path=path, dim=4)
        assert idx2.count == 1
