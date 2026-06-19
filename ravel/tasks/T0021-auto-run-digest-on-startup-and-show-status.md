---
id: T0021
title: Auto-run digest on startup and show status
status: done
dependencies: []
---

# Scope

- The backend runs the digest pipeline automatically on startup. There is no
  frontend trigger. For now it digests from the `samples/` folder; real-email
  (IMAP) ingestion is a later task.
- On startup, run only if there are sample emails not yet digested. If nothing
  is new, skip the run and report the last digest's timestamp.
- Replace `GET /health` with `GET /status`, which reports digest state to the
  frontend:
  - `running`: `{"state": "running", "email_count": N}` — a digest is being
    generated from N emails.
  - `idle`: `{"state": "idle", "last_digest_at": <ISO 8601 UTC>|None}` — no
    run in progress; reports when the last digest finished so the user knows
    how stale the content is. `null` until the first digest exists.
- Frontend: change the dashboard header title to "Hedwig" and make the subtitle
  show the live status message from `/status`.
- Frontend polls `/status` on load. While `running`, re-poll every 30 seconds.
  Once `idle`, stop polling for the rest of the session (digest runs once a
  day; the next day is a new session).

# Acceptance

- Starting the backend with new sample emails runs the digest pipeline
  automatically; `/status` reports `running` with the email count during the
  run and `idle` with the last-run timestamp after it finishes.
- Starting the backend when all sample emails are already digested does not
  re-run the pipeline; `/status` reports `idle` immediately.
- `GET /health` is removed; `GET /status` returns the two shapes above.
- The dashboard header reads "Hedwig" with a subtitle reflecting the current
  status (e.g. "Generating digest from N emails…" while running; "Last digest:
  <date> at <time>" when idle).
- The frontend polls `/status` every 30s only while the status is `running`
  and stops once it becomes `idle`.
- The orphaned `HealthCard` component is removed.
- `pnpm build`, backend lint/type checks, and all tests pass.

# Implementation Notes

- **Startup plumbing**: in `backend/app/main.py`, use the FastAPI `lifespan`
  context manager (preferred over the deprecated `@app.on_event("startup")`).
  Spawn a daemon thread that runs the digest so `/status` stays responsive
  while the LLM pipeline runs — the pipeline is synchronous and takes minutes;
  do not block the lifespan handler.
- **Status state**: introduce a thread-safe module-level status object (a small
  class guarded by `threading.Lock`) in a new `backend/app/status.py`.
  `get_status()` reads it; the runner writes it. Keep it in-memory only — it
  resets each process start, which matches "the next day it is a new session".
- **Refactor the runner**: extract the body of `POST /digest/run`
  (`backend/app/routes/digest_routes.py:109-150`) into a reusable function
  (e.g. `run_digests(source, store, pipeline, ...) -> list[Digest]`) that
  updates the status object — set `running` with the email count at the start,
  set `idle` with `last_digest_at` at the end. Both the startup hook and the
  endpoint call it. Keep `POST /digest/run` for manual/test use; it is no
  longer the primary trigger.
- **"New emails" detection (samples policy)**: enumerate `*.eml` in
  `DEFAULT_SAMPLES_DIR` (`backend/app/ingest/dump.py:18`) and compare their
  `source_id`s (filenames) against the set of already-digested source ids.
  Record digested source ids in a new `ingested_sources(source_id TEXT PRIMARY
  KEY, digest_date TEXT)` table, written as each digest is saved. On startup:
  if any sample filename is not in `ingested_sources`, run; otherwise skip.
  Removed files do not trigger a run (out of scope); only new files do.
- **Email source selection**: add an env switch `EMAIL_SOURCE=samples|imap`
  (default `samples`) and a `get_email_source()` factory returning
  `LocalEmlSource(DEFAULT_SAMPLES_DIR)` for `samples`. For `imap`, leave a
  documented stub that raises `NotImplementedError`. This is the extension
  point for `ImapSource.from_env()` (`backend/app/ingest/imap_source.py:55-72`)
  in the later real-email task.
- **Trigger policy abstraction**: put the "should I run?" decision behind a
  function (e.g. `should_run_digest(source, store) -> bool`) so the later
  real-email task can swap in a daily-schedule policy without touching the
  startup hook.
- **Last-digest timestamp**: add a `generated_at TEXT` column to the `digests`
  table (`backend/app/storage/digest_store.py:46-54`), set to the current UTC
  ISO time on every save. `last_digest_at` in the status is
  `MAX(generated_at)`. The existing `db/hedwig.db` is deleted and recreated by
  the new schema (it is gitignored and disposable; the data will be regenerated
  from samples, and the whole store will be replaced when the IMAP approach
  lands anyway).
- **Future daily-schedule policy (design only — do not implement)**: for real
  email, run once a day at a fixed UTC time aligned with the per-day bucketing
  in `_group_by_day` (`backend/app/routes/digest_routes.py:153-172`), which
  buckets by UTC calendar day. The run for UTC day D should fire shortly after
  the UTC-midnight start of D+1, when day D's emails are all in. If
  `last_digest_at` is before the most recent expected run, run. The later task
  will implement this behind the same `should_run_digest` hook; for now the
  policy is the samples new-files check.
- **Frontend status fetch**: in `frontend/components/digest-card-list.tsx`,
  fetch `/status` via SWR (existing `fetcher` in `frontend/lib/api.ts`). Use
  SWR's `refreshInterval` as a function of the latest data — 30s while
  `state === "running"`, disabled (0) once `idle` — and set
  `revalidateOnFocus: false` so refocusing the tab does not restart polling
  once idle. Render the status text in the header subtitle.
- **Header text**: change `frontend/components/digest-card-list.tsx:45` from
  "Digest history" to "Hedwig". Replace the static subtitle (lines 46-48) with
  the dynamic status line.
- **Remove `GET /health`** at `backend/app/main.py:24-27` and delete the
  orphaned `frontend/components/health-card.tsx` (it polls `/health` and is
  not rendered anywhere).
- **Tests**: cover `should_run_digest` (new files vs. all-digested), the status
  object transitions, `ingested_sources` recording, and the `/status` endpoint
  shapes for both states. The startup thread is hard to test deterministically;
  prefer testing the runner function and policy directly.
