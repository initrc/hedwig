"""FastAPI application entrypoint for the Hedwig backend.

On startup the backend runs the digest pipeline automatically when there are
sample emails not yet digested — see `app.runner.should_run_digest`. The run
happens in a daemon thread so `/status` stays responsive while the LLM
pipeline works (it can take minutes). `GET /status` reports whether a run is in
progress and, when idle, when the last digest was produced.
"""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.ingest.dump import DEFAULT_SAMPLES_DIR
from app.ingest.source import get_email_source, list_local_source_ids
from app.llm.client import OpenAIClient
from app.pipeline.digest import run_pipeline
from app.rag.chroma_store import ChromaStore
from app.rag.embed import embed
from app.routes.chat_routes import chat_router
from app.routes.digest_routes import digest_router
from app.runner import run_digests, should_run_digest
from app.status import digest_status
from app.storage.digest_store import DEFAULT_DB_PATH, DigestStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

_logger = logging.getLogger(__name__)


def startup_digest() -> None:
    """Run a digest in the background if there are new sample emails.

    Reads the available sample filenames (cheap — no parsing), checks the
    policy, and only then spawns the runner on a daemon thread. The thread is a
    daemon so it never blocks process shutdown; a run in flight when the
    process exits is abandoned, which is fine for a once-a-day digest.
    """
    store = DigestStore(db_path=DEFAULT_DB_PATH)
    available = list_local_source_ids(DEFAULT_SAMPLES_DIR)
    if not should_run_digest(available, store):
        _logger.info("No new sample emails; skipping startup digest run.")
        digest_status.set_idle(store.last_digest_at())
        return

    _logger.info("New sample emails found; running digest in the background.")
    vector_store = ChromaStore()
    thread = threading.Thread(
        target=run_digests,
        kwargs={
            "source": get_email_source(DEFAULT_SAMPLES_DIR),
            "store": store,
            "pipeline": run_pipeline,
            "vector_store": vector_store,
            "embed_fn": embed,
            "client": OpenAIClient.get(),
        },
        daemon=True,
        name="startup-digest",
    )
    thread.start()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the startup digest, then serve requests.

    The digest runs on a daemon thread, so yielding to the app happens
    immediately — `/status` can report `running` while the pipeline works.
    """
    startup_digest()
    yield


app = FastAPI(title="Hedwig", lifespan=lifespan)

app.include_router(digest_router)
app.include_router(chat_router)


@app.get("/status")
def status() -> dict[str, object]:
    """Report digest run state to the frontend.

    Returns ``{"state": "running", "email_count": N}`` while a digest is being
    generated, or ``{"state": "idle", "last_digest_at": <ISO>|None}`` when no
    run is in progress (``last_digest_at`` is ``null`` until the first digest
    exists).
    """
    return digest_status.snapshot()

