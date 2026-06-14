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

## Develop

```bash
uv run pytest        # tests
uv run ruff check    # lint
```
