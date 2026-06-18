"""POST /digest/run — ingest, run one pipeline per day, persist, and return the digests.

This is the main endpoint for on-demand digest generation. It ties together the
three pieces built in earlier steps: the local-sample ingestor, the four-stage
pipeline (segment → cluster → summarize → pick-image), and the SQLite store.

Each parsed email is bucketed by the UTC calendar day of its `received_at` and
the pipeline runs once per bucket, so a single request over a samples folder
spanning several days produces one digest per day. The LLM client and the digest
store are both injected via FastAPI dependencies so a test can override them — a
fake client keeps tests off the network, and an in-memory database keeps them
isolated.
"""

import logging
from datetime import UTC
from datetime import date as date_type
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ingest.dump import DEFAULT_SAMPLES_DIR
from app.ingest.parser import ParsedEmail, parse
from app.ingest.source import LocalEmlSource
from app.llm.client import LLMClient, get_client
from app.pipeline.digest import Digest, run_pipeline
from app.rag.chroma_store import ChromaStore
from app.rag.embed import EmbedFn, embed
from app.rag.index import index_digest
from app.rag.store import VectorStore
from app.storage.digest_store import DEFAULT_DB_PATH, DigestStore

digest_router = APIRouter()

_logger = logging.getLogger(__name__)


class DigestRunRequest(BaseModel):
    """Optional overrides for the digest run. Every field has a sensible default.

    Leave the body empty (or omit it) to run every day present in the samples
    folder. Set ``date`` to filter to a single day — only emails received on
    that calendar day are processed, and the response list has zero or one
    entry.
    """

    samples_dir: str | None = None
    date: date_type | None = None


def get_store() -> DigestStore:
    """Build the digest store, pointed at the default database file.

    Override this dependency in tests to point at ``:memory:`` or a temporary
    file instead.
    """
    return DigestStore(db_path=DEFAULT_DB_PATH)


def get_pipeline_runner() -> object:
    """Return the real pipeline runner.

    Returns ``run_pipeline`` typed as ``object`` so FastAPI does not try to
    introspect the callable's parameters as query parameters.  Override this
    dependency in tests to return a stub that yields a fixed ``Digest``.
    """
    return run_pipeline


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Build the ChromaStore once and reuse it across requests.

    Override this dependency in tests to use an in-memory stub instead.
    """
    return ChromaStore()


def get_embed_fn() -> EmbedFn:
    """Return the real embedding function.

    Override this dependency in tests to use a deterministic stub.
    """
    return embed


def get_llm_client() -> LLMClient:
    """Return the shared DeepSeek client for pipeline stages.

    Returns the real client so a reader can trace from the route parameter
    straight to the implementation in one hop.  Override this dependency
    in tests to keep tests off the network.
    """
    return get_client()


@digest_router.get("/digests")
def digests_list(
    store: Annotated[DigestStore, Depends(get_store)],
    limit: int = 10,
) -> list[Digest]:
    """Return the most recent digests, newest date first."""
    return store.list_recent(limit=limit)


@digest_router.post("/digest/run")
def digest_run(
    body: DigestRunRequest,
    store: Annotated[DigestStore, Depends(get_store)],
    pipeline: Annotated[object, Depends(get_pipeline_runner)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embed_fn: Annotated[EmbedFn, Depends(get_embed_fn)],
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> list[Digest]:
    """Run one digest per day: ingest → group by received day → pipeline →
    persist → index → return the list of digests.

    Each email is bucketed by the UTC calendar day of its ``received_at``. The
    pipeline runs once per bucket with that day as the digest date, so a
    request over a folder spanning several days produces several digests.
    Emails with no ``received_at`` are skipped with a warning rather than
    folded into an arbitrary day.

    When ``body.date`` is set, only emails received on that day are processed;
    the returned list has zero or one entry.
    """
    samples_dir = Path(body.samples_dir) if body.samples_dir else DEFAULT_SAMPLES_DIR
    items = [parse(raw) for raw in LocalEmlSource(samples_dir).fetch()]
    buckets = _group_by_day(items)

    if body.date is not None:
        buckets = {day: emails for day, emails in buckets.items() if day == body.date}

    results: list[Digest] = []
    for day in sorted(buckets):
        day_items = sorted(buckets[day], key=lambda item: item.id)
        digest: Digest = pipeline(day_items, date=day, client=client)  # type: ignore[operator]
        store.save(digest)
        try:
            index_digest(digest, vector_store=vector_store, embed_fn=embed_fn)
        except Exception:
            _logger.exception(
                "Failed to index digest dated %s — digest was saved but is not yet searchable",
                digest.date.isoformat(),
            )
        results.append(digest)
    return results


def _group_by_day(items: list[ParsedEmail]) -> dict[date_type, list[ParsedEmail]]:
    """Bucket parsed emails by the UTC calendar day of their ``received_at``.

    Emails with no ``received_at`` (missing or unparseable ``Date`` header) are
    skipped with a WARNING log naming the ``source_id``, so a caller can see
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
