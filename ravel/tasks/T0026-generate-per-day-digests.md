---
id: T0026
title: Generate one digest per day from samples
status: done
dependencies: []
---

# Scope

- Change `POST /digest/run` so it groups the parsed emails by their `Received`
  date (UTC calendar day) and runs the pipeline once **per day**, producing one
  `Digest` per day rather than a single digest over all samples.
- The response shape changes from one `Digest` to `list[Digest]` (one entry per
  day that had at least one email). Update the route, the README, and the
  existing route test accordingly.
- Rework the `date` request field: instead of labeling a single digest, an
  optional `date` filters to that one day (only emails received on that day are
  processed; the response still returns a list, with zero or one entry).

# Acceptance

- `POST /digest/run` with an empty body against the committed `backend/samples`
  produces one digest per distinct `received_at` date present in the folder (7
  digests for the current 8 samples — `20260521`, `20260602`, `20260604`,
  `20260609`, `20260610`, `20260611`, `20260612`), and persists/indexes each.
- Each digest's `date` equals the UTC calendar day of its emails'
  `received_at`, not "today".
- `POST /digest/run` with `"date": "2026-06-09"` processes only the two emails
  received on that day and returns a one-element list.
- Emails whose `received_at` is `None` (missing or unparseable `Date` header)
  are skipped with a logged warning, not silently folded into an arbitrary day.
- The route test covers: multi-day grouping from a mixed-date sample folder,
  `date` filtering to a single day, and the skip-and-warn path for an email
  with no `Date` header. The pipeline runner, store, vector store, embed fn,
  and LLM client remain stubbed via dependency overrides as today.
- `GET /digests` still works unchanged (it lists whatever was persisted).
- `GET /health` still returns 200.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- The parser already gives us the per-email date: `ParsedEmail.received_at` is a
  UTC `datetime` parsed from the `Date` header in
  `backend/app/ingest/parser.py:182` (`_extract_received_at`). Use
  `received_at.astimezone(UTC).date()` to bucket by calendar day. Do not invent
  a new date source.
- The endpoint to change is `digest_run` in
  `backend/app/routes/digest_routes.py:103`. Today it does:
  parse all → `run_pipeline(items, date=body.date, client=client)` →
  `store.save` → `index_digest` → return one `Digest`. Loop that body per day:
  group `items` by day, run the pipeline with each group and that day's date,
  save, index, and collect the `Digest`s into the returned list.
- `run_pipeline` (`backend/app/pipeline/digest.py:88`) already takes a `date`
  argument and defaults it to today — pass the bucket's day explicitly so the
  digest date is the email day, not the run day. Keep the per-day `items` list
  in a stable order (e.g. sorted by `id`) so reruns are reproducible.
- The `date` request field on `DigestRunRequest`
  (`backend/app/routes/digest_routes.py:37`) changes meaning from "label this
  digest" to "only process this day". When set, skip buckets whose day != the
  requested date.
- API contract change: the return type moves from `Digest` to `list[Digest]`.
  Call this out in the README (`backend/README.md` "Run a digest" section,
  lines 28–43) and note the frontend impact — the "Generate digest" button
  wired in T0021 will need to expect a list. Frontend changes are **out of
  scope** for this task; file a follow-up task if needed.
- Edge case: an email with `received_at is None` cannot be bucketed. Skip it
  and log at WARNING with the `source_id` so a user can see which file was
  dropped. Do not put it under today's date — that would be the same
  "everything in one bucket" bug we are fixing.
- Reuse `LocalEmlSource` + `parse` as today; do not re-glob in the route. The
  grouping is a pure post-parse step over the `ParsedEmail` list.
- `index_digest` (`backend/app/rag/index.py`) is already per-digest; just call
  it inside the per-day loop with the same try/except logging the route
  already uses (`digest_routes.py:117-124`).
- The existing test at `backend/tests/routes/test_digest_routes.py` builds one
  `.eml` and asserts on a single returned `Digest`; it must be rewritten for
  the list return, and new cases added for the multi-day grouping, `date`
  filtering, and the no-`Date`-header skip path. Keep using the
  `tests.fakes`/`StubStore`/`stub_embed` factories and dependency overrides.
