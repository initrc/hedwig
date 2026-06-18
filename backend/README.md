# Hedwig backend

FastAPI backend for newsletter ingestion and parsing, managed with [uv](https://docs.astral.sh/uv/).
Plain (non-package) project: code lives in the `app/` package, tests in `tests/`.

## Setup

```bash
uv sync                # creates .venv and installs dependencies
cp .env.example .env   # fill in IMAP credentials when needed (T0003)
```

## Run

```bash
uv run fastapi dev     # auto-discovers app/main.py, starts dev server with reload
```

Then `GET http://127.0.0.1:8000/health` returns `{"status": "ok"}`.

## Parse samples

```bash
uv run python -m app.ingest.dump            # writes db/items.json (one item per samples/*.eml)
uv run python -m app.ingest.dump -o foo.json --samples-dir samples
```

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
