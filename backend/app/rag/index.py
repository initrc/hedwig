"""Read stored digests and index their source texts into a vector store.

`build_index` is the entry point for a full re-index: it reads every digest
from the SQLite store, clears the vector store, chunks, embeds, and inserts.

`index_digest` is the incremental companion: it indexes a single digest
without clearing the store, so newly generated digests become searchable
immediately.

Both functions take their vector store and embedding function as arguments,
so they are testable with fakes and swappable later.
"""

from __future__ import annotations

import logging

from app.pipeline.digest import Digest
from app.rag.chunk import chunk_text
from app.rag.embed import EmbedFn
from app.rag.store import IndexChunk, VectorStore
from app.storage.digest_store import DigestStore

_logger = logging.getLogger(__name__)

# How many digests to pull from the store.  With one digest per day, 365 is
# enough for a year of daily newsletters — far more than the demo holds.  If
# your store has more, raise this limit.
_DIGEST_LIMIT = 365


def _embed_and_insert(
    texts: list[str],
    metadatas: list[dict[str, str | int]],
    *,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
) -> int:
    """Embed a batch of texts and insert them into the vector store.

    Shared by `build_index` (full re-index) and `index_digest`
    (incremental).  Returns the number of chunks inserted, or 0 if
    ``texts`` is empty.
    """
    if not texts:
        return 0

    embeddings = embed_fn(texts)

    chunks: list[IndexChunk] = [
        IndexChunk(text=t, embedding=e, metadata=m)
        for t, e, m in zip(texts, embeddings, metadatas, strict=True)
    ]

    vector_store.insert(chunks)
    return len(chunks)


def build_index(
    *,
    digest_store: DigestStore,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
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

    # Phase 2: embed and insert via the shared helper.
    return _embed_and_insert(
        texts, metadatas, vector_store=vector_store, embed_fn=embed_fn
    )


def index_digest(
    digest: Digest,
    *,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
) -> int:
    """Index a single digest's source texts into the vector store.

    Unlike `build_index`, this does **not** clear the store first — it adds
    chunks incrementally so existing digests remain searchable.  Used by the
    ``/digest/run`` endpoint so every newly generated digest is immediately
    available for chat queries.

    Returns the number of chunks indexed.  A return of 0 means the digest
    had no source text to index (all sources were empty).
    """
    texts: list[str] = []
    metadatas: list[dict[str, str | int]] = []

    digest_date = digest.date.isoformat()
    for topic in digest.topics:
        for source in topic.sources:
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

    count = _embed_and_insert(
        texts, metadatas, vector_store=vector_store, embed_fn=embed_fn
    )
    _logger.info("Indexed %d chunks for digest dated %s", count, digest_date)
    return count
