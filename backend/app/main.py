"""FastAPI application entrypoint for the Hedwig backend.

On startup the backend runs the digest pipeline automatically. The trigger
depends on `EMAIL_SOURCE`: for `samples` it runs when any sample file has not
been folded into a digest yet (`app.runner.should_run_digest`); for `imap` it
runs once a day, when the last digest predates today UTC
(`app.runner.should_run_daily`). In IMAP mode the fetch window resumes from the
last digest's date so a downtime gap is recovered in one fetch, falling back to
`IMAP_INITIAL_SINCE_DAYS` on the very first run. The run happens in a daemon
thread so `/status` stays responsive while the LLM pipeline works (it can take
minutes). `GET /status` reports whether a run is in progress and, when idle,
when the last digest was produced.
"""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC

from dotenv import load_dotenv
from fastapi import FastAPI

from app.ingest.dump import DEFAULT_SAMPLES_DIR
from app.ingest.source import email_source_choice, get_email_source, list_local_source_ids
from app.llm.client import OpenAIClient
from app.pipeline.digest import run_pipeline
from app.rag.chroma_store import ChromaStore
from app.rag.embed import embed
from app.routes.chat_routes import chat_router
from app.routes.digest_routes import digest_router
from app.runner import run_digests, should_run_daily, should_run_digest
from app.status import digest_status
from app.storage.digest_store import DEFAULT_DB_PATH, DigestStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

_logger = logging.getLogger(__name__)


def startup_digest() -> None:
    """Run a digest in the background if the active trigger policy says so.

    For `EMAIL_SOURCE=samples`: run when any sample file has not been digested
    yet (compared by filename, cheap to list without parsing). For
    `EMAIL_SOURCE=imap`: run once a day, when no digest has been produced yet
    today (UTC) — so the first startup of a new day triggers a run and same-day
    restarts do not. The IMAP fetch starts from the last digest's date so a
    downtime gap is recovered in one fetch; on the very first run it falls back
    to `IMAP_INITIAL_SINCE_DAYS`. The run spawns on a daemon thread so it
    never blocks process shutdown; a run in flight when the process exits is
    abandoned, which is fine for a once-a-day digest.
    """
    store = DigestStore(db_path=DEFAULT_DB_PATH)
    choice = email_source_choice()

    if choice == "imap":
        should_run = should_run_daily(store)
        if not should_run:
            _logger.info("Already digested today; skipping startup IMAP digest run.")
            digest_status.set_idle(store.last_digest_at())
            return
        _logger.info("Starting IMAP digest run in the background.")
    else:
        available = list_local_source_ids(DEFAULT_SAMPLES_DIR)
        if not should_run_digest(available, store):
            _logger.info("No new sample emails; skipping startup digest run.")
            digest_status.set_idle(store.last_digest_at())
            return
        _logger.info("New sample emails found; running digest in the background.")

    last_run = store.last_digest_at()
    since = last_run.astimezone(UTC).date() if last_run is not None else None

    vector_store = ChromaStore()
    thread = threading.Thread(
        target=run_digests,
        kwargs={
            "source": get_email_source(DEFAULT_SAMPLES_DIR, since=since),
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
