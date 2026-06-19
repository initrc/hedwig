"""The shared digest runner and the "should I run?" policy.

`run_digests` is the body that both the startup lifespan handler and the
`POST /digest/run` endpoint call. It ingests from an `EmailSource`, runs the
pipeline once per received day, persists each digest, records which source ids
were folded in, and indexes the digest for chat. It also drives the
`DigestStatus` object — `running` with the email count at the start, `idle`
with the last-digest metadata at the end — so `GET /status` always reflects
what the runner is doing.

`should_run_digest` is the trigger policy. For the samples source it is "any
sample file not yet digested"; the later real-email task will swap in a
daily-schedule policy behind this same hook.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC
from datetime import date as date_type

from app.ingest.parser import ParsedEmail, parse
from app.ingest.source import EmailSource
from app.llm.client import LLMClient
from app.pipeline.digest import Digest
from app.rag.embed import EmbedFn
from app.rag.index import index_digest
from app.rag.store import VectorStore
from app.status import DigestStatus, digest_status
from app.storage.digest_store import DigestStore

_logger = logging.getLogger(__name__)

PipelineRunner = Callable[..., Digest]


def should_run_digest(available_source_ids: list[str], store: DigestStore) -> bool:
    """True if any available source id has not been folded into a digest yet.

    The samples policy: enumerate the `source_id`s the source would yield
    (filenames, cheap to list without parsing) and compare against the ids
    already recorded in `ingested_sources`. A new file triggers a run; an
    unchanged folder does not.

    The later real-email task replaces this with a daily-schedule check (run
    once a day at a fixed UTC time if `last_digest_at` predates the expected
    run). The source-id comparison is specific to the samples source.
    """
    ingested = store.ingested_source_ids()
    return any(sid not in ingested for sid in available_source_ids)


def run_digests(
    source: EmailSource,
    store: DigestStore,
    pipeline: PipelineRunner,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
    client: LLMClient | None,
    *,
    date_filter: date_type | None = None,
    status: DigestStatus = digest_status,
) -> list[Digest]:
    """Ingest, run one digest per received day, persist, index, and return them.

    Each email is bucketed by the UTC calendar day of its `received_at`; the
    pipeline runs once per bucket with that day as the digest date. Emails with
    no `received_at` are skipped with a warning. When `date_filter` is set,
    only emails received on that day are processed and the result list has zero
    or one entry.

    The `status` object is updated to `running` with the email count before the
    pipeline runs and back to `idle` with the last-digest metadata when it
    finishes (or on an empty run).
    """
    items = [parse(raw) for raw in source.fetch()]
    buckets = _group_by_day(items)

    if date_filter is not None:
        buckets = {day: emails for day, emails in buckets.items() if day == date_filter}

    email_count = sum(len(emails) for emails in buckets.values())
    status.set_running(email_count)

    results: list[Digest] = []
    try:
        for day in sorted(buckets):
            day_items = sorted(buckets[day], key=lambda item: item.id)
            digest = pipeline(day_items, date=day, client=client)
            store.save(digest)
            store.record_ingested_sources([item.id for item in day_items], day)
            try:
                index_digest(digest, vector_store=vector_store, embed_fn=embed_fn)
            except Exception:
                _logger.exception(
                    "Failed to index digest dated %s — digest was saved but is not yet searchable",
                    digest.date.isoformat(),
                )
            results.append(digest)
    finally:
        status.set_idle(store.last_digest_at())

    return results


def _group_by_day(items: list[ParsedEmail]) -> dict[date_type, list[ParsedEmail]]:
    """Bucket parsed emails by the UTC calendar day of their `received_at`.

    Emails with no `received_at` (missing or unparseable `Date` header) are
    skipped with a WARNING log naming the `source_id`, so a caller can see
    which file was dropped instead of having it silently folded into an
    arbitrary day.
    """
    buckets: dict[date_type, list[ParsedEmail]] = {}
    for item in items:
        if item.received_at is None:
            _logger.warning(
                "Skipping email %s: no received_at date (missing or unparseable "
                "Date header); cannot assign to a daily digest.",
                item.id,
            )
            continue
        day = item.received_at.astimezone(UTC).date()
        buckets.setdefault(day, []).append(item)
    return buckets
