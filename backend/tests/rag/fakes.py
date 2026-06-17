"""Test stubs for the RAG layer: a deterministic embedding function and an
in-memory vector store.

These let tests exercise indexing and retrieval without touching a real embedding
API or a real Chroma database.  ``StubStore`` implements the full ``VectorStore``
Protocol (including ``search`` via brute-force cosine similarity), so it works as
a drop-in for any RAG test.

Keep these separate from ``tests/fakes.py``, which owns LLM fakes and
domain-object factories.  The two layers are tested independently and should not
couple through shared test scaffolding.
"""

from __future__ import annotations

import hashlib
import math

from app.rag.store import ChunkResult, IndexChunk


def stub_embed(texts: list[str]) -> list[list[float]]:
    """Return a fixed 3-dimensional vector for each text.

    Uses MD5 (not Python's ``hash()``) so the vectors are stable across
    interpreter runs.  Different texts get different vectors; identical texts
    get identical vectors.
    """
    dim = 3
    return [
        [float(b) / 255.0 for b in hashlib.md5(t.encode()).digest()[:dim]]
        for t in texts
    ]


class StubStore:
    """An in-memory ``VectorStore`` backed by a plain Python list.

    ``search`` does brute-force cosine similarity over all stored chunks.
    This is slow for large datasets but perfectly fine for tests, and it keeps
    the dependency list empty.

    ``delete_all_calls`` and ``insert_calls`` are counters so tests can assert
    that the indexing flow called the right methods.
    """

    def __init__(self) -> None:
        self._chunks: list[IndexChunk] = []
        self.delete_all_calls = 0
        self.insert_calls = 0

    # -- public test helpers ---------------------------------------------------

    @property
    def chunks(self) -> list[IndexChunk]:
        """A copy of the stored chunks, for test assertions."""
        return list(self._chunks)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    # -- VectorStore interface -------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        *,
        k: int,
        where: dict[str, str | int] | None = None,
    ) -> list[ChunkResult]:
        scored: list[tuple[float, IndexChunk]] = []
        for chunk in self._chunks:
            if where:
                if not all(
                    chunk.metadata.get(key) == value
                    for key, value in where.items()
                ):
                    continue
            score = _cosine_similarity(query_vector, chunk.embedding)
            scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:k]

        return [
            ChunkResult(text=chunk.text, metadata=chunk.metadata, score=score)
            for score, chunk in top
        ]

    def insert(self, chunks: list[IndexChunk]) -> None:
        self._chunks.extend(chunks)
        self.insert_calls += 1

    def delete_all(self) -> None:
        self._chunks.clear()
        self.delete_all_calls += 1


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Brute-force cosine similarity between two equal-length vectors."""
    dot = sum(ai * bi for ai, bi in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
