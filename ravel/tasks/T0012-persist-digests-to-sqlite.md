---
id: T0012
title: Persist digests to SQLite
status: done
dependencies:
  - T0011
---

# Scope

- Persist the full `Digest` object (from T0011) so it survives process restarts and Day 4's dashboard can read
  it back. Store the **whole** object — the card is a projection of a few fields, but the detail panel and the
  Day 3 RAG layer need the rest.
- Provide save + load functions: write a `Digest`, and read it (and/or the most recent / by-date) back as a
  validated `Digest`.

# Acceptance

- A SQLite-backed store exists with functions to save a `Digest` and to load it back (at least: load by id or
  date, and list recent digests). A loaded digest re-validates as the same `Digest` model.
- The full digest object is persisted (not just card fields) and round-trips: save → load → equal to the
  original after Pydantic re-validation.
- The DB file path is configurable and defaults to a sensible local location; the DB file is gitignored.
- Tests run against a temporary/in-memory SQLite database (no shared on-disk state) and cover: save then load
  returns an equal `Digest`; listing returns saved digests. No real API calls (construct `Digest` fixtures
  directly).
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 step 6 (lines 133–134): "Persist the full digest
  object (Postgres for the 'real' version; SQLite is fine). Store the *full* object — the card is just a
  projection." SQLite is the right call for this build — zero infra, and the interface can be swapped for
  Postgres later.
- Input type: `Digest` from `backend/app/pipeline/digest.py` (T0011). Suggested module:
  `backend/app/storage/digests.py` (a new `app.storage` package).
- **Simplest sufficient schema:** a single table with the digest `id`/`date` as columns plus a JSON column
  holding `digest.model_dump_json()`. This sidesteps a per-field relational mapping (overkill for a projection
  the frontend reads whole) and keeps "store the full object" literal. Use the stdlib `sqlite3` module —
  no ORM dependency needed for this shape.
- **Round-trip via Pydantic, not pickle:** persist `model_dump_json()` and reload with
  `Digest.model_validate_json(...)`, mirroring how `dump.py` already serializes items
  (`backend/app/ingest/dump.py:25` uses `item.model_dump(mode="json")`).
- **DB path + gitignore:** default to something like `backend/out/hedwig.db` (the `out/` dir is already where
  `dump.py` writes — `dump.py:19`). Confirm the DB file is gitignored; T0001's root `.gitignore` may not cover
  `*.db`, so add a pattern if needed.
- **Test isolation:** accept the DB path/connection as a parameter so tests can pass `":memory:"` or a
  `tmp_path` file; never write to the default location during tests.
- Initialize the table lazily (create-if-not-exists on first use) so callers and the T0013 endpoint don't need
  a separate migration step.
- Out of scope: the HTTP endpoint (T0013) and generating digests (T0011). This task only reads/writes an
  already-built `Digest`.
