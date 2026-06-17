"""Tests for `app.rag.index` — the `build_index` function.

Every test uses fakes from ``tests.rag.fakes`` so no real embedding API or
Chroma database is touched.
"""

from __future__ import annotations

from datetime import date

from app.rag.index import build_index
from app.rag.store import IndexChunk
from app.storage.digest_store import DigestStore
from tests.fakes import _digest, _digest_source, _digest_topic
from tests.rag.fakes import StubStore, stub_embed

# -- build_index tests -------------------------------------------------------


def test_build_index_clears_store_before_indexing() -> None:
    """Re-running build_index calls delete_all before inserting new chunks."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        _digest(
            topics=[
                _digest_topic(
                    sources=[
                        _digest_source(clean_text="Some newsletter text.")
                    ]
                )
            ]
        )
    )

    fake_store = StubStore()

    # First run: should clear and insert.
    count = build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )
    assert count > 0
    assert fake_store.delete_all_calls == 1
    first_chunk_count = fake_store.chunk_count

    # Second run: should clear again and re-insert, same count (idempotent).
    build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )
    assert fake_store.delete_all_calls == 2
    # After clearing and re-inserting, count should match (not doubled).
    assert fake_store.chunk_count == first_chunk_count


def test_build_index_stores_expected_metadata() -> None:
    """Each indexed chunk carries digest_date, topic_label, source_id,
    source_subject, and chunk_index."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        _digest(
            digest_date=date(2026, 6, 15),
            topics=[
                _digest_topic(
                    label="Rate Cuts",
                    sources=[
                        _digest_source(
                            source_id="finance.eml",
                            source="finance@news.com",
                            subject="Daily Finance Brief",
                            clean_text=(
                                "The Fed signaled potential rate cuts in the "
                                "upcoming September meeting, citing slowing "
                                "inflation and a cooling labor market."
                            ),
                        )
                    ],
                )
            ],
        )
    )

    fake_store = StubStore()
    build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert fake_store.chunk_count == 1
    chunk = fake_store.chunks[0]
    assert chunk.metadata["digest_date"] == "2026-06-15"
    assert chunk.metadata["topic_label"] == "Rate Cuts"
    assert chunk.metadata["source_id"] == "finance.eml"
    assert chunk.metadata["source_subject"] == "Daily Finance Brief"
    assert chunk.metadata["chunk_index"] == 0
    assert "Fed signaled potential rate cuts" in chunk.text


def test_build_index_chunks_long_text() -> None:
    """A source with text longer than CHUNK_SIZE produces multiple chunks with
    sequential chunk_index values."""
    # Build text that's clearly longer than one chunk.
    sentence = "Market update number {n}: conditions are stable. "
    long_text = "".join(sentence.format(n=i) for i in range(200))

    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        _digest(
            topics=[
                _digest_topic(
                    label="Markets",
                    sources=[_digest_source(clean_text=long_text)],
                )
            ]
        )
    )

    fake_store = StubStore()
    count = build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert count > 1
    indices = [c.metadata["chunk_index"] for c in fake_store.chunks]
    assert indices == list(range(len(indices)))


def test_build_index_skips_empty_source_text() -> None:
    """Sources with empty or whitespace-only clean_text produce no chunks."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        _digest(
            topics=[
                _digest_topic(
                    label="Empty",
                    sources=[
                        _digest_source(clean_text="   "),
                        _digest_source(clean_text="Real content here."),
                    ],
                )
            ]
        )
    )

    fake_store = StubStore()
    count = build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    # Only the non-empty source should produce chunks.
    assert count == 1
    assert fake_store.chunk_count == 1
    assert "Real content" in fake_store.chunks[0].text


def test_build_index_returns_zero_for_empty_store() -> None:
    """When no digests have been saved, build_index returns 0."""
    digest_store = DigestStore(db_path=":memory:")
    fake_store = StubStore()

    count = build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert count == 0
    assert fake_store.chunk_count == 0
    # delete_all should still have been called (idempotent).
    assert fake_store.delete_all_calls == 1


def test_build_index_indexes_multiple_digests_and_topics() -> None:
    """Chunks from different digests and topics all land in the store."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        _digest(
            digest_date=date(2026, 6, 15),
            topics=[
                _digest_topic(
                    label="Topic A",
                    sources=[_digest_source(source_id="a.eml", clean_text="Text A.")],
                ),
                _digest_topic(
                    label="Topic B",
                    sources=[_digest_source(source_id="b.eml", clean_text="Text B.")],
                ),
            ],
        )
    )
    digest_store.save(
        _digest(
            digest_date=date(2026, 6, 16),
            topics=[
                _digest_topic(
                    label="Topic C",
                    sources=[_digest_source(source_id="c.eml", clean_text="Text C.")],
                )
            ],
        )
    )

    fake_store = StubStore()
    count = build_index(
        digest_store=digest_store,
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert count == 3
    dates = {c.metadata["digest_date"] for c in fake_store.chunks}
    assert dates == {"2026-06-15", "2026-06-16"}
    topics = {c.metadata["topic_label"] for c in fake_store.chunks}
    assert topics == {"Topic A", "Topic B", "Topic C"}


# -- StubStore.search tests (sanity check) ----------------------------


def test_search_returns_chunks_ordered_by_similarity() -> None:
    store = StubStore()
    store.insert([
        IndexChunk(
            text="Apple stock rises on earnings beat.",
            embedding=[1.0, 0.0, 0.0],
            metadata={"topic": "tech"},
        ),
        IndexChunk(
            text="Fed holds rates steady.",
            embedding=[0.0, 1.0, 0.0],
            metadata={"topic": "finance"},
        ),
    ])

    # Query vector close to the second chunk.
    results = store.search([0.1, 0.9, 0.0], k=2)
    assert len(results) == 2
    assert results[0].text == "Fed holds rates steady."
    assert results[0].score > results[1].score


def test_search_filters_by_metadata_when_where_is_given() -> None:
    store = StubStore()
    store.insert([
        IndexChunk(
            text="Apple news.",
            embedding=[1.0, 0.0, 0.0],
            metadata={"topic": "tech"},
        ),
        IndexChunk(
            text="Fed news.",
            embedding=[1.0, 0.0, 0.0],  # same vector
            metadata={"topic": "finance"},
        ),
    ])

    results = store.search([1.0, 0.0, 0.0], k=5, where={"topic": "finance"})
    assert len(results) == 1
    assert results[0].text == "Fed news."


def test_search_returns_empty_list_when_store_is_empty() -> None:
    store = StubStore()
    results = store.search([1.0, 0.0, 0.0], k=5)
    assert results == []
