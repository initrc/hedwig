---
id: T0003
title: Implement ImapSource for Gmail
status: done
dependencies:
  - T0002
---

# Scope

- Implement `ImapSource` satisfying the `EmailSource` interface from T0002.
- Connect to Gmail via IMAP using credentials loaded from `.env` (`IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`).
- Support filtering: at minimum by date range (e.g., last N days) and by sender list, so we don't ingest the whole mailbox.

# Acceptance

- `ImapSource(host, port, username, password, since: date | None, senders: list[str] | None)` connects, fetches matching messages, and yields them via the `EmailSource` interface.
- Credentials are read via `python-dotenv` from `.env`; the class itself takes plain args so it stays testable.
- Running a small smoke script against `dshi.news@gmail.com` successfully fetches at least one message and prints its subject. (Smoke script can live under `scripts/` and is not part of the automated test suite.)
- Automated tests cover argument plumbing and filter construction using a mocked IMAP client (no live network in CI).
- `uv run pytest` passes; `uv run ruff check` passes.
- `.env` is not committed (verify); `.env.example` already documents the variables (added in T0001).

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 2 (lines 87–91), marked optional ("Build if time; the local source is enough to proceed") and first on the cut-list (line 194).
- Use stdlib `imaplib` (`IMAP4_SSL`) — adequate for Gmail and avoids extra deps. If `imaplib`'s search syntax proves painful, `imap-tools` is a reasonable upgrade, but try stdlib first.
- Gmail requires an **app password** (not the account password) since 2-step verification is required. The user will provide this out-of-band and store it in `.env` locally.
- Map IMAP UIDs to the `source_id` field on the `RawEmail` wrapper so re-fetches stay idempotent.
- For the smoke script, default to `since = 14 days ago` and pull `INBOX` to avoid surprises.
- Do NOT log credentials or full message bodies at INFO level. Redact `IMAP_PASSWORD` from any error output.
- Out of scope: persistence of fetched messages, deduping against prior runs, OAuth. Keep this a thin fetcher.
