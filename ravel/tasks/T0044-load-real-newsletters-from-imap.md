---
id: T0044
title: Load real newsletters from IMAP at startup
status: done
dependencies: []
---

# Scope

- Wire `EMAIL_SOURCE=imap` end-to-end so the backend ingests real newsletters from a mailbox instead of `samples/*.eml`. The `ImapSource` fetcher itself already exists (T0003); this task connects it.
- Add a sender allowlist env var (comma-separated newsletter sender emails) so `ImapSource` only fetches messages from subscribed newsletters, not the whole inbox. This is the filter the build plan calls out and the one piece currently missing from `.env.example`.
- Add a date-window env var (days back to fetch) feeding `ImapSource.since`, so a real mailbox isn't trawled in its entirety on every run.
- Make the startup trigger work in IMAP mode. Today `startup_digest` decides whether to run by listing local `.eml` filenames (`list_local_source_ids`) — a samples-specific policy that is meaningless for IMAP. Swap in a daily-schedule policy (run once a day when `last_digest_at` predates the expected run) behind the existing `should_run_digest` hook when `EMAIL_SOURCE=imap`.

# Acceptance

- `EMAIL_SOURCE=imap` produces an `ImapSource` from `get_email_source()` instead of raising `NotImplementedError`. The sender allowlist and `since` window are read from env and passed through to `ImapSource`.
- `.env.example` documents the new env vars (`IMAP_SENDERS` sender allowlist and `IMAP_INITIAL_SINCE_DAYS` first-run fallback) and updates the existing "not yet wired" comment on `EMAIL_SOURCE=imap` to reflect that it is now wired.
- `startup_digest` uses a policy appropriate to the selected source: the existing samples policy for `EMAIL_SOURCE=samples`, and a daily-schedule policy for `EMAIL_SOURCE=imap`. Restarting the backend the same day does not re-run; a restart the next day does. When the server has been down for multiple days, the fetch starts from the last digest's date so the full gap is recovered in one run.
- Existing `test_get_email_source_imap_not_implemented` is replaced with a test asserting `get_email_source()` returns an `ImapSource` (env mocked, no network). New tests cover the daily-schedule trigger policy with a mocked `DigestStore`.
- `uv run pytest` passes; `uv run ruff check` passes; `uv run mypy` passes.
- A smoke run against the throwaway inbox with `EMAIL_SOURCE=imap` and a real sender allowlist fetches only newsletters from the configured senders and produces a digest. (Smoke check is manual; not part of the automated suite.)

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 2 (lines 87–91) — `ImapSource` was marked optional and is first on the cut-list (line 221). This task lands the cut-list item.
- T0003 delivered the fetcher but deliberately left wiring and dedupe out of scope (`backend/app/ingest/imap_source.py:1` module docstring). The `NotImplementedError` at `backend/app/ingest/source.py:80` is the exact extension point; its comment points at "T0021 implementation notes", and T0021's notes (`ravel/tasks/T0021-auto-run-digest-on-startup-and-show-status.md` line 69) point back at "the later real-email task" — this is that task.
- `ImapSource.from_env()` (`backend/app/ingest/imap_source.py:55`) already accepts `since` and `senders` args. Either read the new env vars inside `from_env` (keeping `get_email_source` thin) or read them in `get_email_source` and pass them through — pick one and keep the other call sites consistent.
- Suggested env var names, matching the existing `IMAP_*` prefix: `IMAP_SENDERS` (comma-separated sender emails, e.g. `news@stratechery.com,digest@axios.com`) and `IMAP_INITIAL_SINCE_DAYS` (days back on the very first run when no prior digest exists to resume from; defaults to 1). Empty `IMAP_SENDERS` should be a loud error in IMAP mode — an unfiltered mailbox fetch is the failure mode this var exists to prevent.
- Startup trigger: `startup_digest` (`backend/app/main.py:43`) currently calls `list_local_source_ids(DEFAULT_SAMPLES_DIR)` unconditionally. Branch on `EMAIL_SOURCE`: keep the samples path as-is, and for `imap` call a daily-schedule check against `store.last_digest_at()` instead. `should_run_digest` (`backend/app/runner.py:38`) is the natural home for the new policy branch — its docstring already says "the later real-email task replaces this with a daily-schedule check."
- **Gap recovery:** when `last_digest_at` exists, the IMAP fetch start date is set to `last_digest_at.date()` (UTC) so a multi-day downtime gap is recovered in a single fetch — `run_digests` groups by received day and produces one digest per day. The first-ever run (no prior digest) falls back to `IMAP_INITIAL_SINCE_DAYS`. The `since` value threads from `startup_digest` → `get_email_source(since=...)` → `ImapSource.from_env(since=...)`. When `since` is passed explicitly, `from_env` skips the env-var fallback.
- Do NOT add persistence, cross-run dedupe, or OAuth to `ImapSource` — still out of scope per T0003. The pipeline already records ingested source ids (`runner.run_digests` → `store.record_ingested_sources`), so a same-day re-run that re-fetches the same UIDs will still skip already-processed items at the pipeline level.
- Never log `IMAP_PASSWORD` or full message bodies. `ImapSource` already redacts the password on login failure (`imap_source.py:101`); keep that behavior intact.
