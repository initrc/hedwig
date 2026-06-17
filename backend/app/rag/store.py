"""The `VectorStore` Protocol and the data types that cross its boundary.

`VectorStore` is the interface the RAG layer programs against.  Chroma is the
first implementation (see `chroma_store.py`), but callers only ever see this
protocol.  That keeps retrieval and indexing decoupled from the particular
store, the same way `EmailSource` decouples ingestion from IMAP vs. local files.
"""

from typing import Protocol

from pydantic import BaseModel


class IndexChunk(BaseModel):
    """A chunk headed *into* the vector store, carrying its pre-computed embedding.

    `metadata` carries the fields the retriever and answer-generator need to
    produce citations: which newsletter, which date, which topic, and where in the
    source text this chunk sits.
    """

    text: str
    embedding: list[float]
    metadata: dict[str, str | int]


class ChunkResult(BaseModel):
    """A chunk returned *from* the vector store after a similarity search.

    `score` is a similarity score where higher means more relevant (the Chroma
    implementation converts its native cosine distance to this convention).
    """

    text: str
    metadata: dict[str, str | int]
    score: float


class VectorStore(Protocol):
    """Store and search text chunks by embedding similarity.

    Three operations: `insert` to add chunks (with their pre-computed
    embeddings and metadata), `search` to find the top-*k* closest chunks, and
    `delete_all` to clear the store before a re-index.
    """

    def search(
        self,
        query_vector: list[float],
        *,
        k: int,
        where: dict[str, str | int] | None = None,
    ) -> list[ChunkResult]:
        """Return the top-*k* chunks whose embeddings are closest to
        `query_vector`, optionally filtered to matching metadata fields.

        Results are ordered by descending similarity score.
        """
        ...

    def insert(self, chunks: list[IndexChunk]) -> None:
        """Add chunks (with their embeddings and metadata) to the store.

        A second call with the same logical chunks adds duplicates — it is the
        caller's job to clear first when idempotency is needed.
        """
        ...

    def delete_all(self) -> None:
        """Remove every chunk from the store so a re-index starts clean."""
        ...
