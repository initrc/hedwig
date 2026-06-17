"""POST /digest/run — ingest, run the pipeline, persist, and return the digest.

This is the main endpoint for on-demand digest generation. It ties together the
three pieces built in earlier steps: the local-sample ingestor, the four-stage
pipeline (segment → cluster → summarize → pick-image), and the SQLite store.

The LLM client and the digest store are both injected via FastAPI dependencies so
a test can override them — a fake client keeps tests off the network, and an
in-memory database keeps them isolated.
"""

import logging
from collections.abc import Callable
from datetime import date as date_type
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ingest.dump import DEFAULT_SAMPLES_DIR
from app.ingest.parser import parse
from app.ingest.source import LocalEmlSource
from app.pipeline.digest import Digest, run_pipeline
from app.rag.chroma_store import ChromaStore
from app.rag.embed import embed
from app.rag.index import index_digest
from app.rag.store import VectorStore
from app.storage.digest_store import DEFAULT_DB_PATH, DigestStore

digest_router = APIRouter()

_logger = logging.getLogger(__name__)


class DigestRunRequest(BaseModel):
    """Optional overrides for the digest run. Every field has a sensible default.

    Leave the body empty (or omit it) to run with the committed samples and
    today's date.
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


def get_embed_fn() -> Callable[[list[str]], list[list[float]]]:
    """Return the real embedding function.

    Override this dependency in tests to use a deterministic stub.
    """
    return embed


@digest_router.post("/digest/run")
def digest_run(
    body: DigestRunRequest,
    store: Annotated[DigestStore, Depends(get_store)],
    pipeline: Annotated[object, Depends(get_pipeline_runner)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    embed_fn: Annotated[Callable[[list[str]], list[list[float]]], Depends(get_embed_fn)],
) -> Digest:
    """Run a full digest: ingest → parse → pipeline → persist → index → return."""
    samples_dir = Path(body.samples_dir) if body.samples_dir else DEFAULT_SAMPLES_DIR
    items = [parse(raw) for raw in LocalEmlSource(samples_dir).fetch()]
    digest: Digest = pipeline(items, date=body.date)  # type: ignore[operator]
    store.save(digest)
    try:
        index_digest(digest, vector_store=vector_store, embed_fn=embed_fn)
    except Exception:
        _logger.exception(
            "Failed to index digest dated %s — digest was saved but is not "
            "yet searchable",
            digest.date.isoformat(),
        )
    return digest
