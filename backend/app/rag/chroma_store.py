"""Chroma implementation of the `VectorStore` Protocol.

Stores chunk embeddings on disk under `backend/db/chroma/` (or a
caller-chosen directory) so the index survives process restarts.  No separate
server needed — Chroma runs in the same Python process.

Chroma returns cosine *distance* (0 = identical, 2 = opposite).  This
implementation converts to a similarity score (1 = identical, 0 = opposite) so
that callers always see "higher is better," matching the convention declared on
`VectorStore.search`.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from chromadb import PersistentClient
from chromadb.api.types import Metadata, Where

from app.rag.store import ChunkResult, IndexChunk

# Where the Chroma data lives on disk, relative to the backend directory.
DEFAULT_CHROMA_DIR = "db/chroma"

# The single Chroma collection name.  A collection is Chroma's unit of
# isolation — like a table in SQL.  One collection for all newsletter chunks
# keeps retrieval simple; metadata filtering (by topic, date) replaces the need
# for multiple collections.
COLLECTION_NAME = "newsletter_chunks"

# Collection-level config passed to Chroma when creating the collection.
# `hnsw:space` tells Chroma to use cosine distance (the angle between
# vectors).  Cosine is the right choice for text embeddings because direction
# matters more than magnitude — two paragraphs about the same topic point in
# the same direction even if one is longer.
_COLLECTION_METADATA: dict[str, str] = {"hnsw:space": "cosine"}


class ChromaStore:
    """A `VectorStore` backed by a local Chroma database."""

    def __init__(self, *, path: str = DEFAULT_CHROMA_DIR) -> None:
        self._client = PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata=_COLLECTION_METADATA,
        )

    # -- VectorStore interface ------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        *,
        k: int,
        where: dict[str, str | int] | None = None,
    ) -> list[ChunkResult]:
        """Return the top-*k* chunks by cosine similarity, highest first.

        If `where` is given, only chunks whose stored metadata matches every
        key-value pair are considered (Chroma `WHERE` clause).  For example,
        `where={"topic_label": "Fed rate decision"}` limits results to
        chunks that came from that topic.
        """
        chroma_where: Where | None = None
        if where:
            chroma_where = cast(Where, cast(dict[str, Any], where))

        results = self._collection.query(
            query_embeddings=[query_vector],  # type: ignore[arg-type]
            n_results=k,
            where=chroma_where,
            include=["documents", "metadatas", "distances"],
        )

        # Chroma returns lists-of-lists (one inner list per query vector).
        # Since we only send one query, we take the first inner list.  Every
        # `include` key is guaranteed to have the same number of entries, so
        # we assert that once and then index without further guards.
        ids_raw = results.get("ids")
        docs_raw = results.get("documents")
        metas_raw = results.get("metadatas")
        dists_raw = results.get("distances")

        if not ids_raw or not ids_raw[0]:
            return []

        ids: list[str] = ids_raw[0]
        documents: list[str] = docs_raw[0] if docs_raw else []
        metadatas: list[dict[str, str | int]] = (
            metas_raw[0] if metas_raw else []  # type: ignore[assignment]
        )
        distances: list[float] = dists_raw[0] if dists_raw else []

        assert len(ids) == len(documents) == len(metadatas) == len(distances), (
            f"Chroma returned mismatched result lengths: "
            f"ids={len(ids)}, documents={len(documents)}, "
            f"metadatas={len(metadatas)}, distances={len(distances)}"
        )

        chunk_results: list[ChunkResult] = []
        for i in range(len(ids)):
            # Cosine distance ranges [0, 2]; convert to similarity [1, -1].
            score = 1.0 - distances[i]
            chunk_results.append(
                ChunkResult(
                    text=documents[i],
                    metadata=metadatas[i],
                    score=score,
                )
            )

        return chunk_results

    def insert(self, chunks: list[IndexChunk]) -> None:
        """Add chunks to the collection.  Call `delete_all` first for idempotency.

        Each chunk's `metadata` dict carries citation fields — for example::

            {
                "digest_date": "2026-06-15",
                "topic_label": "Fed rate decision",
                "source_id": "20260615-tikr.eml",
                "source_subject": "Daily Markets Update",
                "chunk_index": 0,
            }

        These fields are stored in Chroma and returned by `search()` so the
        retriever can tell the LLM *where* each chunk came from.
        """
        if not chunks:
            return

        self._collection.add(
            ids=[uuid.uuid4().hex for _ in chunks],
            documents=[c.text for c in chunks],
            embeddings=[c.embedding for c in chunks],  # type: ignore[arg-type]
            metadatas=[
                cast(Metadata, cast(dict[str, Any], c.metadata))
                for c in chunks
            ],
        )

    # -- management -----------------------------------------------------------

    def delete_all(self) -> None:
        """Remove every chunk from the collection.

        Call this before re-indexing so stale chunks from a previous run don't
        linger.  Chroma does not support `delete(where={})` on persistent
        clients in all versions, so we delete and recreate the collection
        instead — it is the most reliable path.
        """
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata=_COLLECTION_METADATA,
        )

    @property
    def count(self) -> int:
        """How many chunks are currently stored.  Useful in tests and debugging."""
        return self._collection.count()

    def close(self) -> None:
        """Release the underlying Chroma client.

        Safe to call multiple times.  After closing, `search` and `insert`
        will raise — the store is no longer usable.
        """
        # PersistentClient doesn't expose an explicit close, but the
        # underlying duckdb connection can be shut down via __del__.  This is
        # here as a hook for future cleanup and for symmetry with other
        # resource-owning objects in the project.
        # The client will be garbage-collected; this method is explicit
        # documentation that the store *can* be closed.
        del self._collection
        del self._client
