---
id: T0013
title: Expose POST /digest/run endpoint
status: new
dependencies:
  - T0011
  - T0012
---

# Scope

- Add the `POST /digest/run` FastAPI endpoint that ties Day 2 together: ingest the local samples → parse →
  run the pipeline (T0011) → persist the digest (T0012) → return the digest as JSON. This is the build plan's
  stated end-of-day deliverable.
- Wire it on the existing FastAPI app alongside `/health`.

# Acceptance

- `POST /digest/run` exists on the app, runs ingest → parse → `run_pipeline` → persist, and returns the
  resulting `Digest` as JSON (FastAPI serializes the Pydantic model).
- The endpoint persists the digest via the T0012 store before returning, so a subsequent load returns the same
  digest.
- A test exercises the route via `TestClient` with the LLM/pipeline stubbed (no real API calls) and a
  temporary DB, asserting a 200 and a response body matching the `Digest` schema, and that the digest was
  persisted.
- `GET /health` still returns 200 (no regression).
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 end-of-day (line 135): "a `POST /digest/run` endpoint
  that ingests → produces → persists a digest."
- App entry point: `backend/app/main.py` (the `app` and `/health` route, lines 8–14). Add the route here or in
  a small router module imported by `main` — match whichever keeps `main.py` clean as routes grow.
- **Compose existing pieces, add no new LLM logic:**
  - Ingest + parse: `LocalEmlSource(samples_dir).fetch()` → `parse(...)`, exactly as `dump.py` does
    (`backend/app/ingest/dump.py:24`). The default samples dir is `backend/samples` (`dump.py:18`,
    `DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"`). Reuse `dump_items`/the parser
    rather than duplicating the glob.
  - Produce: `run_pipeline(items, ...)` from T0011 (`backend/app/pipeline/digest.py`).
  - Persist: the save function from T0012 (`backend/app/storage/digests.py`).
- **Testability over the network:** the pipeline makes real LLM calls, so the route test must inject stubs.
  Prefer FastAPI dependency injection (`Depends`) for the pipeline runner and the digest store so the test
  overrides them via `app.dependency_overrides` — this also lets the test point persistence at a temporary
  DB. Use `fastapi.testclient.TestClient` (the `fastapi[standard]` extra bundles `httpx`, established in
  T0001).
- **Long-running call:** generating a digest is several sequential LLM calls and can take many seconds.
  Synchronous is acceptable for this on-demand endpoint (Day 4 wires a "Generate digest" button to it). Note,
  but don't build, that it could move to a background task later — keep scope to the synchronous version.
- Consider accepting an optional request body to override the samples dir / date for testing, defaulting to
  the committed samples — but keep it minimal.
- Out of scope: Day 4's frontend button, Day 3's RAG/chat endpoints, and any IMAP-sourced run (the local
  source is enough, per the build plan's cut-order list, lines 199–205).
