"""Read stored digests and index their source texts into a vector store.

`build_index` is the entry point: it reads every digest from the SQLite store,
chunks each source's clean text, embeds the chunks, and pushes them into the
vector store.  It clears the store first so re-running is idempotent.

This module deliberately does not depend on any particular vector store or
embedding provider — it takes both as arguments.  That makes it testable with
fakes and swappable later.
"""

import logging
from collections.abc import Callable

from app.rag.chunk import chunk_text
from app.rag.store import IndexChunk, VectorStore
from app.storage.digest_store import DigestStore

_logger = logging.getLogger(__name__)

# How many digests to pull from the store.  With one digest per day, 365 is
# enough for a year of daily newsletters — far more than the demo holds.  If
# your store has more, raise this limit.
_DIGEST_LIMIT = 365


def build_index(
    *,
    digest_store: DigestStore,
    vector_store: VectorStore,
    embed_fn: Callable[[list[str]], list[list[float]]],
) -> int:
    """Index all stored digest source texts into `vector_store`.

    Steps:
    1. Clear the vector store (idempotent re-index).
    2. Read every digest from `digest_store`.
    3. For each topic → source, chunk the `clean_text`.
    4. Embed all chunks in one batch call to `embed_fn`.
    5. Insert the chunks into `vector_store`.

    Returns the number of chunks indexed.  A return of 0 means there were no
    digests (or all sources had empty text).
    """
    vector_store.delete_all()

    digests = digest_store.list_recent(limit=_DIGEST_LIMIT + 1)
    if len(digests) > _DIGEST_LIMIT:
        _logger.warning(
            "Digest store has more than %d digests; only the most recent "
            "%d will be indexed.  Raise _DIGEST_LIMIT to index more.",
            _DIGEST_LIMIT,
            _DIGEST_LIMIT,
        )
        digests = digests[:_DIGEST_LIMIT]

    if not digests:
        return 0

    # Phase 1: collect every (text, metadata) pair across all digests.
    texts: list[str] = []
    metadatas: list[dict[str, str | int]] = []

    for digest in digests:
        digest_date = digest.date.isoformat()
        for topic in digest.topics:
            for _i, source in enumerate(topic.sources):
                text = source.clean_text.strip()
                if not text:
                    continue
                for chunk_idx, chunk in enumerate(chunk_text(text)):
                    texts.append(chunk)
                    metadatas.append({
                        "digest_date": digest_date,
                        "topic_label": topic.label,
                        "source_id": source.id,
                        "source_subject": source.subject,
                        "chunk_index": chunk_idx,
                    })

    if not texts:
        return 0

    # Phase 2: embed all texts in one batch.
    embeddings = embed_fn(texts)

    # Phase 3: build IndexChunks and insert.
    index_chunks: list[IndexChunk] = []
    for text, embedding, metadata in zip(texts, embeddings, metadatas, strict=True):
        index_chunks.append(
            IndexChunk(text=text, embedding=embedding, metadata=metadata)
        )

    vector_store.insert(index_chunks)
    return len(index_chunks)
