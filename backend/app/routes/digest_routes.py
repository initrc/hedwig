"""POST /digest/run — ingest, run the pipeline, persist, and return the digest.

This is the main endpoint for on-demand digest generation. It ties together the
three pieces built in earlier steps: the local-sample ingestor, the four-stage
pipeline (segment → cluster → summarize → pick-image), and the SQLite store.

The LLM client and the digest store are both injected via FastAPI dependencies so
a test can override them — a fake client keeps tests off the network, and an
in-memory database keeps them isolated.
"""

from datetime import date as date_type
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ingest.dump import DEFAULT_SAMPLES_DIR
from app.ingest.parser import parse
from app.ingest.source import LocalEmlSource
from app.pipeline.digest import Digest, run_pipeline
from app.storage.digest_store import DEFAULT_DB_PATH, DigestStore

digest_router = APIRouter()


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


@digest_router.post("/digest/run")
def digest_run(
    body: DigestRunRequest,
    store: Annotated[DigestStore, Depends(get_store)],
    pipeline: Annotated[object, Depends(get_pipeline_runner)],
) -> Digest:
    """Run a full digest: ingest → parse → pipeline → persist → return."""
    samples_dir = Path(body.samples_dir) if body.samples_dir else DEFAULT_SAMPLES_DIR
    items = [parse(raw) for raw in LocalEmlSource(samples_dir).fetch()]
    digest: Digest = pipeline(items, date=body.date)  # type: ignore[operator]
    store.save(digest)
    return digest
