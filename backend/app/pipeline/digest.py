"""Define the final `Digest` schema and the pipeline that assembles it.

The four pipeline stages each do one thing: segment emails into stories, group
stories into topics, summarize each topic, and pick an image. This module wires
them together into `run_pipeline`, a single entry point that takes a day's
`ParsedEmail`s and returns one validated `Digest`.

No new LLM prompts live here — this is pure composition of the four existing
stages and assembly of their typed outputs into the final schema.
"""

from datetime import UTC, date, datetime

from pydantic import BaseModel

from app.ingest.parser import CandidateImage, ParsedEmail
from app.llm.client import LLMClient
from app.pipeline.cluster import cluster
from app.pipeline.image import gather_candidates, select_image
from app.pipeline.segment import segment_items
from app.pipeline.summarize import Source, summarize_topics

# Feature flag: topic image selection is disabled because the chosen images are
# often inaccurate or pixelated. The code is kept so we can revisit later.
_SELECT_TOPIC_IMAGES = False


class DigestSource(BaseModel):
    """A newsletter that contributed to a topic, with enough for the "view original" link.

    Carried per-topic in `DigestTopic.sources`. `original_url` opens the
    publisher's hosted page; when it is ``None`` the frontend shows `clean_text`
    as a fallback in-app view.
    """

    id: str
    source: str
    subject: str
    original_url: str | None
    clean_text: str


class DigestTopic(BaseModel):
    """One topic in the digest: its label, summary, sources, and selected image.

    `label` comes from clustering, `summary` and `sources` from summarization,
    and `image` from image selection (``None`` when no candidate illustrates the
    story).
    """

    label: str
    summary: str
    sources: list[DigestSource]
    image: CandidateImage | None = None


class Digest(BaseModel):
    """The finished daily digest: a date and its topics."""

    date: date
    topics: list[DigestTopic]


def _resolve_digest_sources(
    sources: list[Source], emails_by_id: dict[str, ParsedEmail]
) -> list[DigestSource]:
    """Turn each citation's `source_item_id` into a `DigestSource` with the
    full fields the frontend needs.

    A source whose id is not in `emails_by_id` is skipped rather than crashing,
    because the summarizer's own citation check already guards against invented
    ids and a missing email at this point is a data-integrity edge case, not a
    bug in the pipeline.
    """
    resolved: list[DigestSource] = []
    for source in sources:
        email = emails_by_id.get(source.source_item_id)
        if email is None:
            continue
        resolved.append(
            DigestSource(
                id=email.id,
                source=email.source,
                subject=email.subject,
                original_url=email.original_url,
                clean_text=email.clean_text,
            )
        )
    return resolved


def run_pipeline(
    items: list[ParsedEmail],
    *,
    date: date | None = None,
    client: LLMClient | None = None,
) -> Digest:
    """Run the full pipeline and return one validated `Digest`.

    Wires segment → cluster → summarize → image-select, then assembles each
    topic's projection into the final schema. `date` defaults to today in UTC;
    pass an override for reproducible/testable runs. `client` is passed through
    to every stage so a test can stub the whole pipeline with a single fake
    connection.
    """
    if date is None:
        date = datetime.now(UTC).date()

    emails_by_id = {item.id: item for item in items}

    stories = segment_items(items, client=client)
    topics = cluster(stories, client=client)
    summaries = summarize_topics(topics, client=client)

    result_topics: list[DigestTopic] = []
    for topic, summary in zip(topics, summaries, strict=True):
        if _SELECT_TOPIC_IMAGES:
            candidates = gather_candidates(topic, emails_by_id)
            image = select_image(topic, candidates, client=client)
        else:
            image = None
        sources = _resolve_digest_sources(summary.sources, emails_by_id)

        result_topics.append(
            DigestTopic(
                label=summary.label,
                summary=summary.summary,
                sources=sources,
                image=image,
            )
        )

    return Digest(date=date, topics=result_topics)
