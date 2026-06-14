---
id: T0001
title: Scaffold Python backend with uv and dotenv
status: done
dependencies: []
---

# Scope

- Initialize a Python backend project under `backend/` using `uv` for dependency and virtualenv management.
- Add baseline dependencies: `fastapi[standard]`, `pydantic`, `beautifulsoup4`, `python-dotenv`.
- Add a `.env.example` documenting the IMAP-related variables that will be needed in T0003 (no real secrets).
- Ensure `.env` is gitignored.
- Add a minimal FastAPI `app` with a `/health` endpoint so the server runs end-to-end.

# Acceptance

- `uv sync` installs dependencies cleanly into a local `.venv`, and `uv run ruff check` reports no lint errors (`ruff` is a dev dep with a minimal config).
- `uv run fastapi dev` starts the server (auto-discovers `app/main.py`, auto-reload) and `GET /health` returns 200.
- `uv run pytest` passes.
- `.env.example` is committed with placeholder values only; `.env` is not (verify via `git check-ignore .env`).
- `pyproject.toml` is committed with pinned/minimum versions for the listed deps.

# Implementation Notes

- Project layout: backend code lives under `backend/` to keep the future Next.js frontend (Day 4) cleanly separated at `frontend/`. Structure:
  - `backend/app/` — the FastAPI application package (`app/main.py` defines `app`; `app/__init__.py` present).
  - `backend/tests/` — tests in a dedicated directory, with an (empty) `tests/__init__.py`.
- Use a **plain (non-package) project** — `uv init` app mode, i.e. **no `[build-system]` table and no editable install**. This is a runnable service, not a library published to PyPI, so packaging metadata is unnecessary overhead.
  - How tests import the app without installing the package: `tests/__init__.py` makes pytest (default "prepend" import mode) walk the `__init__.py` chain up to the project root and put `backend/` on `sys.path`, so `from app.main import app` resolves. No `[tool.pytest.ini_options] pythonpath` and no editable install are needed. (Verified empirically: removing `tests/__init__.py` reintroduces `ModuleNotFoundError: app`.)
  - Naming the package `app/` (rather than `src/hedwig/`) lets `uv run fastapi dev` auto-discover `app/main.py` with no path argument, matching the official full-stack-fastapi-template convention.
  - History: earlier iterations used `uv init --app` (broke tests → `pythonpath` hack) then `uv init --package` + `src/` (installable, but heavier than needed). Settled on the lighter non-package layout above, which is sufficient for an application.
- Use `fastapi[standard]` (i.e. `uv add fastapi --extra standard`) rather than bare `fastapi`. The `standard` extra bundles `uvicorn`, the `fastapi` CLI (`fastapi dev`/`fastapi run`), `httpx` (used by `TestClient`), and other common runtime deps. `pydantic`, `beautifulsoup4`, and `python-dotenv` are also declared explicitly since they are imported directly rather than relied on transitively.
- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 1 (lines 85–86).
- `.env.example` lists (with placeholder values only):
  - `IMAP_HOST=imap.gmail.com`
  - `IMAP_PORT=993`
  - `IMAP_USERNAME=` (Gmail app username; real value lives in `.env` only)
  - `IMAP_PASSWORD=` (Gmail app password; real value lives in `.env` only)
- Root `.gitignore` covers `.env`, `.venv/`, `__pycache__/`, `*.pyc`. The repo already gitignores `samples/` — leave that alone.
- Do not add an LLM SDK yet; that lands in T0005+ (Day 2 work).
