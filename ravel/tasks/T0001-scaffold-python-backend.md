---
id: T0001
title: Scaffold Python backend with uv and dotenv
status: new
dependencies: []
---

# Scope

- Initialize a Python backend project at the repo root (or `backend/` — see Implementation Notes) using `uv` for dependency and virtualenv management.
- Add baseline dependencies: `fastapi`, `uvicorn`, `pydantic`, `beautifulsoup4`, `python-dotenv`.
- Add a `.env.example` documenting the IMAP-related variables that will be needed in T0003 (no real secrets).
- Ensure `.env` is gitignored.
- Add a minimal FastAPI `app` with a `/health` endpoint so the server runs end-to-end.

# Acceptance

- `uv sync` installs dependencies cleanly into a local `.venv`.
- `uv run uvicorn <app-import-path>:app --reload` starts the server and `GET /health` returns 200.
- `.env.example` is committed; `.env` is not (verify via `git check-ignore .env`).
- `pyproject.toml` is committed with pinned/minimum versions for the listed deps.
- Project builds (i.e., `uv sync` succeeds) and there are no lint errors from a basic `ruff check` (add `ruff` as a dev dep and a minimal config).

# Implementation Notes

- Project layout: place backend code under `backend/` to keep the future Next.js frontend (Day 4) cleanly separated at `frontend/`. The package lives at `backend/hedwig/` (flat layout — no `src/` wrapper, since this is a runnable FastAPI app, not a published library).
- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 1 (lines 85–86).
- Use `uv init --package` or `uv init --app` — pick `--app` since we want a runnable FastAPI server, not a publishable library.
- `.env.example` should list (with placeholder values):
  - `IMAP_HOST=imap.gmail.com`
  - `IMAP_PORT=993`
  - `IMAP_USERNAME=` (Gmail app username; real value lives in `.env` only)
  - `IMAP_PASSWORD=` (Gmail app password; real value lives in `.env` only)
- Confirm root `.gitignore` covers `.env`, `.venv/`, `__pycache__/`, `*.pyc`. The repo already gitignores `samples/` (see commit 934d735) — leave that alone.
- Do not add an LLM SDK yet; that lands in T0005+ (Day 2 work).
