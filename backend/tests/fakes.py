"""Shared test helpers: domain-object factories and `make_schema_instruction`.

The pure client stubs (`FakeClient`, `QueuedFakeClient`, `model_reply*`) live
in `app/llm/fake_client.py` — import them from there directly.
"""

from datetime import UTC, datetime
from datetime import date as date_type
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from app.ingest.parser import CandidateImage, ParsedEmail
from app.pipeline.cluster import Topic as ClusterTopic
from app.pipeline.digest import Digest, DigestSource, DigestTopic
from app.pipeline.segment import Story


def make_schema_instruction(messages: list[ChatCompletionMessageParam]) -> str:
    """Return the schema-instruction system message `ask()` prepends.

    `ask()` always inserts a system message describing the JSON shape ahead of
    the caller's messages. Selecting it by role (rather than by a fixed index)
    keeps these assertions stable if the prepending order ever changes.
    """
    systems = [
        m for m in cast(list[dict[str, object]], messages) if m.get("role") == "system"
    ]
    assert len(systems) >= 1
    return str(systems[0]["content"])


# ---------------------------------------------------------------------------
# domain-object factories — minimal valid instances for tests that need a
# digest, topic, source, or image without running the full pipeline.
# ---------------------------------------------------------------------------


def make_image(
    url: str,
    *,
    alt: str = "",
    width: int | None = None,
    height: int | None = None,
) -> CandidateImage:
    """A minimal candidate image, matching the model's own defaults."""
    return CandidateImage(url=url, alt=alt, width=width, height=height)


def make_digest_source(
    *,
    source_id: str = "test.eml",
    source: str = "news@test.com",
    subject: str = "Test Subject",
    original_url: str | None = "https://example.com/view/1",
    clean_text: str = "Body text.",
) -> DigestSource:
    """A minimal digest source (the per-topic "view original" link)."""
    return DigestSource(
        id=source_id,
        source=source,
        subject=subject,
        original_url=original_url,
        clean_text=clean_text,
    )


def make_digest_topic(
    *,
    label: str = "Test Topic",
    summary: str = "A test summary.",
    sources: list[DigestSource] | None = None,
    image: CandidateImage | None = None,
) -> DigestTopic:
    """A minimal digest topic (one row in the digest card)."""
    return DigestTopic(
        label=label,
        summary=summary,
        sources=sources or [],
        image=image,
    )


def make_digest(
    *,
    digest_date: date_type | None = None,
    topics: list[DigestTopic] | None = None,
) -> Digest:
    """A minimal digest for a given date (defaults to 2026-06-15)."""
    return Digest(
        date=digest_date or date_type(2026, 6, 15),
        topics=topics or [],
    )


def make_story(
    story_id: str | None = None,
    *,
    source_item_id: str = "news.eml",
    title: str = "Title",
    text: str = "Body.",
) -> Story:
    """A minimal story in a newsletter.  The id defaults to ``{source_item_id}#0``."""
    return Story(
        id=story_id if story_id is not None else f"{source_item_id}#0",
        source_item_id=source_item_id,
        title=title,
        text=text,
    )


def make_topic(
    label: str = "Some topic",
    *,
    stories: list[Story] | None = None,
) -> ClusterTopic:
    """A minimal cluster topic (a group of related stories)."""
    return ClusterTopic(label=label, stories=stories or [])


def make_parsed_email(
    *,
    item_id: str = "news.eml",
    source: str = "news@example.com",
    subject: str = "Daily digest",
    received_at: datetime | None = None,
    clean_text: str = "Body text.",
    candidate_images: list[CandidateImage] | None = None,
    original_url: str | None = "https://example.com/view/1",
) -> ParsedEmail:
    """A minimal parsed email (as returned by the ingestion parser)."""
    if received_at is None:
        received_at = datetime(2026, 6, 15, tzinfo=UTC)
    return ParsedEmail(
        id=item_id,
        source=source,
        subject=subject,
        received_at=received_at,
        clean_text=clean_text,
        candidate_images=candidate_images or [],
        original_url=original_url,
    )
