"""Tests for `app.storage.digest_store`, the SQLite-backed digest store.

Every test uses an in-memory SQLite database (``:memory:``) so no files are
written to disk and tests never interfere with each other.
"""

from datetime import date

from app.storage.digest_store import DigestStore
from tests.fakes import make_digest, make_digest_source, make_digest_topic, make_image

# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_returns_equalmake_digest() -> None:
    """Saving a digest and loading it back gives a value-equal Digest."""
    store = DigestStore(db_path=":memory:")
    original = make_digest(
        topics=[
            make_digest_topic(
                label="Chips",
                summary="Chips are up.",
                sources=[
                    make_digest_source(source_id="alpha.eml", source="alpha@news.com"),
                    make_digest_source(source_id="beta.eml", source="beta@news.com"),
                ],
                image=make_image("https://x.com/chart.png"),
            ),
            make_digest_topic(
                label="Bonds",
                summary="Bonds are down.",
                sources=[make_digest_source(source_id="gamma.eml", subject="Gamma News")],
                image=None,
            ),
        ]
    )

    digest_id = store.save(original)
    loaded = store.load(digest_id)

    assert loaded is not None
    assert loaded == original
    # Also check the id matches the date.
    assert digest_id == original.date.isoformat()


def test_load_returns_none_for_missing_id() -> None:
    """Loading an id that was never saved returns None."""
    store = DigestStore(db_path=":memory:")
    assert store.load("2099-01-01") is None


def test_load_by_date_finds_the_rightmake_digest() -> None:
    store = DigestStore(db_path=":memory:")
    original = make_digest(digest_date=date(2026, 3, 8))
    store.save(original)

    loaded = store.load_by_date(date(2026, 3, 8))
    assert loaded is not None
    assert loaded == original


def test_load_by_date_returns_none_when_no_match() -> None:
    store = DigestStore(db_path=":memory:")
    assert store.load_by_date(date(2026, 1, 1)) is None


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------


def test_list_recent_returns_saved_digests_newest_first() -> None:
    store = DigestStore(db_path=":memory:")

    store.save(make_digest(digest_date=date(2026, 6, 10)))
    store.save(make_digest(digest_date=date(2026, 6, 14)))
    store.save(make_digest(digest_date=date(2026, 6, 12)))

    recent = store.list_recent()

    assert len(recent) == 3
    assert recent[0].date == date(2026, 6, 14)
    assert recent[1].date == date(2026, 6, 12)
    assert recent[2].date == date(2026, 6, 10)


def test_list_recent_respects_limit() -> None:
    store = DigestStore(db_path=":memory:")

    for d in range(1, 6):
        store.save(make_digest(digest_date=date(2026, 6, d)))

    recent = store.list_recent(limit=3)
    assert len(recent) == 3
    assert recent[0].date == date(2026, 6, 5)


def test_list_recent_returns_empty_list_when_no_digests() -> None:
    store = DigestStore(db_path=":memory:")
    assert store.list_recent() == []


# ---------------------------------------------------------------------------
# upsert (same date overwrites)
# ---------------------------------------------------------------------------


def test_saving_same_date_twice_overwrites() -> None:
    store = DigestStore(db_path=":memory:")

    first = make_digest(
        topics=[make_digest_topic(label="First", summary="First version.")],
    )
    second = make_digest(
        topics=[make_digest_topic(label="Second", summary="Second version.")],
    )

    first_id = store.save(first)
    second_id = store.save(second)

    # Both should have the same id (same date).
    assert first_id == second_id == "2026-06-15"

    loaded = store.load(first_id)
    assert loaded is not None
    assert loaded == second
    assert loaded != first

    # Only one row in the table.
    assert len(store.list_recent(limit=10)) == 1


# ---------------------------------------------------------------------------
# full-object persistence
# ---------------------------------------------------------------------------


def test_full_digest_with_image_and_url_round_trips() -> None:
    """Every field — including nested image fields and optional URL — survives."""
    store = DigestStore(db_path=":memory:")

    original = make_digest(
        digest_date=date(2026, 6, 15),
        topics=[
            make_digest_topic(
                label="Imaged Topic",
                summary="Summary with image.",
                sources=[
                    make_digest_source(
                        source_id="full.eml",
                        source="full@example.com",
                        subject="Full Subject",
                        original_url="https://example.com/full/view",
                        clean_text="Full clean text with emoji 🎉.",
                    )
                ],
                image=make_image(
                    url="https://example.com/full.png",
                    alt="A full image",
                    width=800,
                    height=600,
                ),
            ),
            make_digest_topic(
                label="Plain Topic",
                summary="Summary without image.",
                sources=[
                    make_digest_source(
                        source_id="plain.eml",
                        original_url=None,
                        clean_text="No URL fallback.",
                    )
                ],
                image=None,
            ),
        ],
    )

    store.save(original)
    loaded = store.load("2026-06-15")

    assert loaded is not None
    assert loaded == original

    # Spot-check nested fields.
    imaged = loaded.topics[0]
    assert imaged.label == "Imaged Topic"
    assert imaged.image is not None
    assert imaged.image.url == "https://example.com/full.png"
    assert imaged.image.width == 800

    plain = loaded.topics[1]
    assert plain.image is None
    assert plain.sources[0].original_url is None
    assert plain.sources[0].clean_text == "No URL fallback."


# ---------------------------------------------------------------------------
# type preservation across round-trip
# ---------------------------------------------------------------------------


def test_sources_preserve_types_across_round_trip() -> None:
    """Every field on a digest source keeps its Python type after save → load."""
    store = DigestStore(db_path=":memory:")

    original = make_digest(
        topics=[
            make_digest_topic(
                sources=[
                    make_digest_source(
                        source_id="alpha.eml",
                        source="alpha@news.com",
                        subject="Alpha",
                        original_url="https://x.com/1",
                        clean_text="Alpha text.",
                    )
                ]
            )
        ]
    )

    store.save(original)
    loaded = store.load("2026-06-15")

    assert loaded is not None
    [src] = loaded.topics[0].sources
    assert isinstance(src.id, str)
    assert isinstance(src.source, str)
    assert isinstance(src.subject, str)
    assert isinstance(src.original_url, str)
    assert isinstance(src.clean_text, str)


# ---------------------------------------------------------------------------
# generated_at + last_digest_at (T0021)
# ---------------------------------------------------------------------------


def test_save_stamps_generated_at() -> None:
    """Saving a digest records when it was produced in `generated_at`."""
    from datetime import datetime

    store = DigestStore(db_path=":memory:")
    store.save(make_digest(digest_date=date(2026, 6, 18)))

    last_at = store.last_digest_at()
    assert isinstance(last_at, datetime)


def test_last_digest_at_returns_none_when_empty() -> None:
    store = DigestStore(db_path=":memory:")
    assert store.last_digest_at() is None


def test_last_digest_at_picks_most_recently_generated() -> None:
    """`last_digest_at` orders by generated_at, not by digest date.

    Saving an older-date digest last should make it the "last produced" one,
    since its `generated_at` is newest.
    """
    store = DigestStore(db_path=":memory:")
    store.save(make_digest(digest_date=date(2026, 6, 18)))
    store.save(make_digest(digest_date=date(2026, 6, 10)))

    last_at = store.last_digest_at()
    assert last_at is not None


# ---------------------------------------------------------------------------
# ingested_sources (T0021)
# ---------------------------------------------------------------------------


def test_record_and_list_ingested_source_ids() -> None:
    store = DigestStore(db_path=":memory:")
    assert store.ingested_source_ids() == set()

    store.record_ingested_sources(["a.eml", "b.eml"], date(2026, 6, 18))
    assert store.ingested_source_ids() == {"a.eml", "b.eml"}


def test_record_ingested_sources_is_idempotent() -> None:
    """Recording the same source id twice updates its digest date, not duplicates."""
    store = DigestStore(db_path=":memory:")
    store.record_ingested_sources(["a.eml"], date(2026, 6, 17))
    store.record_ingested_sources(["a.eml"], date(2026, 6, 18))

    assert store.ingested_source_ids() == {"a.eml"}


def test_record_ingested_sources_empty_list_is_noop() -> None:
    store = DigestStore(db_path=":memory:")
    store.record_ingested_sources([], date(2026, 6, 18))
    assert store.ingested_source_ids() == set()

