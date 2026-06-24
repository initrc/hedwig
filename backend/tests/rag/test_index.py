"""Tests for `app.rag.index` — the `build_index` and `index_digest` functions.

Every test uses fakes from ``tests.rag.fakes`` so no real embedding API or
Chroma database is touched.
"""

from __future__ import annotations

from datetime import date

from app.rag.index import build_index, index_digest
from app.rag.store import IndexChunk
from app.storage.digest_store import DigestStore
from tests.fakes import make_digest, make_digest_source, make_digest_topic, make_story_source
from tests.rag.fakes import StubStore, stub_embed

# -- build_index tests -------------------------------------------------------


def test_build_index_clears_store_before_indexing() -> None:
    """Re-running build_index calls delete_all before inserting new chunks."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        make_digest(
            topics=[
                make_digest_topic(
                    sources=[make_digest_source()],
                    story_sources=[make_story_source(text="Some newsletter text.")],
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
        make_digest(
            digest_date=date(2026, 6, 15),
            topics=[
                make_digest_topic(
                    label="Rate Cuts",
                    sources=[
                        make_digest_source(
                            source_id="finance.eml",
                            subject="Daily Finance Brief",
                        )
                    ],
                    story_sources=[
                        make_story_source(
                            text=(
                                "The Fed signaled potential rate cuts in the "
                                "upcoming September meeting, citing slowing "
                                "inflation and a cooling labor market."
                            ),
                            source_item_id="finance.eml",
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
    """A story with text longer than CHUNK_SIZE produces multiple chunks with
    sequential chunk_index values."""
    sentence = "Market update number {n}: conditions are stable. "
    long_text = "".join(sentence.format(n=i) for i in range(200))

    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        make_digest(
            topics=[
                make_digest_topic(
                    label="Markets",
                    sources=[make_digest_source()],
                    story_sources=[make_story_source(text=long_text)],
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


def test_build_index_skips_empty_story_text() -> None:
    """Stories with empty or whitespace-only text produce no chunks."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        make_digest(
            topics=[
                make_digest_topic(
                    label="Empty",
                    sources=[make_digest_source()],
                    story_sources=[
                        make_story_source(text="   "),
                        make_story_source(text="Real content here."),
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

    # Only the non-empty story should produce chunks.
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
    assert fake_store.delete_all_calls == 1


def test_build_index_indexes_multiple_digests_and_topics() -> None:
    """Chunks from different digests and topics all land in the store."""
    digest_store = DigestStore(db_path=":memory:")
    digest_store.save(
        make_digest(
            digest_date=date(2026, 6, 15),
            topics=[
                make_digest_topic(
                    label="Topic A",
                    sources=[make_digest_source(source_id="a.eml")],
                    story_sources=[make_story_source(text="Text A.", source_item_id="a.eml")],
                ),
                make_digest_topic(
                    label="Topic B",
                    sources=[make_digest_source(source_id="b.eml")],
                    story_sources=[make_story_source(text="Text B.", source_item_id="b.eml")],
                ),
            ],
        )
    )
    digest_store.save(
        make_digest(
            digest_date=date(2026, 6, 16),
            topics=[
                make_digest_topic(
                    label="Topic C",
                    sources=[make_digest_source(source_id="c.eml")],
                    story_sources=[make_story_source(text="Text C.", source_item_id="c.eml")],
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


# -- index_digest tests ----------------------------------------------------


def test_index_digest_does_not_clear_store() -> None:
    """index_digest adds chunks without calling delete_all."""
    fake_store = StubStore()

    index_digest(
        make_digest(
            digest_date=date(2026, 6, 15),
            topics=[
                make_digest_topic(
                    label="Topic A",
                    sources=[make_digest_source()],
                    story_sources=[make_story_source(text="First digest text.")],
                )
            ],
        ),
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert fake_store.delete_all_calls == 0
    first_count = fake_store.chunk_count
    assert first_count == 1

    # Index a second digest — should add without clearing.
    index_digest(
        make_digest(
            digest_date=date(2026, 6, 16),
            topics=[
                make_digest_topic(
                    label="Topic B",
                    sources=[make_digest_source()],
                    story_sources=[make_story_source(text="Second digest text.")],
                )
            ],
        ),
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert fake_store.delete_all_calls == 0
    assert fake_store.chunk_count == 2


def test_index_digest_stores_expected_metadata() -> None:
    """Each chunk from index_digest carries digest_date, topic_label,
    source_id, source_subject, and chunk_index."""
    fake_store = StubStore()

    index_digest(
        make_digest(
            digest_date=date(2026, 6, 15),
            topics=[
                make_digest_topic(
                    label="Rate Cuts",
                    sources=[
                        make_digest_source(
                            source_id="finance.eml",
                            subject="Daily Finance Brief",
                        )
                    ],
                    story_sources=[
                        make_story_source(
                            text=(
                                "The Fed signaled potential rate cuts in the "
                                "upcoming September meeting."
                            ),
                            source_item_id="finance.eml",
                        )
                    ],
                )
            ],
        ),
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
    assert "Fed signaled" in chunk.text


def test_index_digest_skips_empty_story_text() -> None:
    """Stories with whitespace-only text produce no chunks."""
    fake_store = StubStore()

    count = index_digest(
        make_digest(
            topics=[
                make_digest_topic(
                    label="Empty",
                    sources=[make_digest_source()],
                    story_sources=[
                        make_story_source(text="   "),
                        make_story_source(text="Real content here."),
                    ],
                )
            ]
        ),
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert count == 1
    assert fake_store.chunk_count == 1
    assert "Real content" in fake_store.chunks[0].text


def test_index_digest_returns_zero_for_digest_with_no_text() -> None:
    """A digest whose stories all have empty text returns 0."""
    fake_store = StubStore()

    count = index_digest(
        make_digest(
            topics=[
                make_digest_topic(
                    label="All Empty",
                    sources=[make_digest_source()],
                    story_sources=[
                        make_story_source(text="   "),
                        make_story_source(text=""),
                    ],
                )
            ]
        ),
        vector_store=fake_store,
        embed_fn=stub_embed,
    )

    assert count == 0
    assert fake_store.chunk_count == 0
    assert fake_store.insert_calls == 0


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
            embedding=[1.0, 0.0, 0.0],
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
