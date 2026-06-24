# Hedwig backend

FastAPI backend for newsletter ingestion and parsing, managed with [uv](https://docs.astral.sh/uv/).
Plain (non-package) project: code lives in the `app/` package, tests in `tests/`.

## Setup

```bash
uv sync                # creates .venv and installs dependencies
cp .env.example .env   # fill in API keys; set IMAP_* vars for real-email ingestion
```

## Run

```bash
uv run fastapi dev     # auto-discovers app/main.py, starts dev server with reload
```

On startup the backend runs the digest pipeline automatically when there are
emails to process (see `EMAIL_SOURCE` in `.env`). The trigger depends on the
chosen source:

- **samples** (default): runs when any `.eml` file in `backend/samples/` has
  not yet been digested. Adding a new file triggers a re-run; an unchanged
  folder does not.
- **imap**: runs once per UTC day. The fetch starts from the last digest's
  date so a downtime gap is recovered in one run; on the very first run it
  looks back `IMAP_INITIAL_SINCE_DAYS` days. Requires `IMAP_SENDERS` (sender
  allowlist) and Gmail app-password credentials (`IMAP_USERNAME`,
  `IMAP_PASSWORD`).

The run happens in a background thread so the server stays responsive.
`GET /status` reports what is happening:

- `{"state": "running", "email_count": N}` while a digest is being generated.
- `{"state": "idle", "last_digest_at": "<ISO>"}` when no run is in progress (`null` until the first digest exists).

Restarting the server with `EMAIL_SOURCE=samples` does not re-run the pipeline
unless a new `.eml` file has been added to `samples/` — already-digested source
ids are recorded in the database so the startup check is idempotent. With
`EMAIL_SOURCE=imap`, restarting the same UTC day does not re-run; the next day
triggers a fresh run.

## Parse samples

```bash
uv run python -m app.ingest.dump            # writes db/items.json (one item per samples/*.eml)
uv run python -m app.ingest.dump -o foo.json --samples-dir samples
```

## Run a digest manually

The digest runs automatically on startup (above). `POST /digest/run` is kept
for manual and test use — it ingests the committed samples, runs the pipeline
against DeepSeek, and persists + indexes one digest **per day** found in the
samples:

```bash
curl -X POST http://127.0.0.1:8000/digest/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

The empty body parses every `samples/*.eml`, groups them by the UTC calendar
day of their `Received` date, and runs the pipeline once per day. The response
is a JSON array of `Digest` objects (one per day that had at least one email),
each persisted to `db/hedwig.db` and indexed into Chroma. Emails with no
parseable `Date` header are skipped with a logged warning.

Override `"date": "2026-06-18"` to process only emails received on that one day
(the response list then has zero or one entry), or `"samples_dir"` to point at
another folder. `GET /digests` lists the most recent persisted digests.

## Develop

```bash
uv run pytest        # tests
uv run ruff check    # lint
uv run mypy          # type check
```

## Scripts

`scripts/fetch_imap_smoke.py` is a manual smoke test for the IMAP fetcher
(`app.ingest.imap_source.ImapSource`). It hits the live network, so it is **not**
part of the automated suite. Fill in real `IMAP_*` credentials in `.env` (a Gmail
app password), then run it from `backend/`:

```bash
uv run python scripts/fetch_imap_smoke.py
```

It fetches the last 14 days of `INBOX` and prints each message's UID and subject.
