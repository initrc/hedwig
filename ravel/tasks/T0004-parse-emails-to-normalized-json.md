---
id: T0004
title: Parse emails into normalized items and dump to JSON
status: done
dependencies:
  - T0002
---

# Scope

- Build a parser that takes a `RawEmail` from any `EmailSource` and produces a normalized item:
  `{id, source, subject, received_at, clean_text, candidate_images: [{url, alt, width, height}], original_url}`.
- Strip HTML into readable text (BeautifulSoup + a readability pass).
- Collect candidate images with `url`, `alt`, `width`, `height`. Do NOT pick the "best" image — that's Day 2's LLM step. Filter obvious junk: images with width or height < ~100px (logos / tracking pixels).
- Provide a CLI entry point (e.g., `uv run python -m app.ingest.dump`) that runs `LocalEmlSource` over `samples/` and writes parsed items to a JSON file (path configurable; default `out/items.json`).

# Acceptance

- A `parse(raw: RawEmail) -> ParsedEmail` function exists and returns a Pydantic model matching the schema above.
- `clean_text` is plain readable text with HTML tags removed and whitespace collapsed; quoted-printable and base64 transfer encodings are decoded correctly.
- `candidate_images` includes only images with both dimensions ≥ 100 when dimensions are known, or unknown-dimension images that aren't 1×1 tracking pixels. `alt` may be empty string but never missing.
- `original_url` is extracted from the first prominent "View in browser" / "Read online" link when present, else `null`.
- `received_at` is timezone-aware (UTC).
- Running the CLI over the committed `samples/*.eml` files produces a JSON file with one item per `.eml`, each validating against the Pydantic model.
- Unit tests cover: HTML→text, image filtering threshold, missing-fields fallbacks, and one round-trip on a fixture `.eml`.
- `uv run pytest` passes; `uv run ruff check` passes.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 3 (lines 91–96) and step 4 (line 97).
- Suggested module: `backend/app/ingest/parser.py` for the parser, `backend/app/ingest/dump.py` for the CLI (the backend package is `app`, established by T0002).
- For readability extraction, `readability-lxml` is the simplest pick on top of BeautifulSoup. Add it to deps in this task.
- Image dimensions: prefer the `width`/`height` HTML attributes; if absent, leave as `None` and let the filter keep the image (don't fetch the URL to measure — adds network + flakiness).
- `samples/*.eml` are real-world newsletter HTML and will surface most edge cases. Design the parser to handle the full directory without per-file tweaks.
- `samples/` is committed (no longer gitignored). Before committing any newly-added `.eml`, scrub the subscriber email address `real.name@gmail.com` with these two commands, run from inside `samples/`:
  ```bash
  sed -i '' 's/real\.name@gmail\.com/reader@example.com/g' *.eml
  sed -i '' 's/real\.name=gmail\.com/reader=example.com/g' *.eml
  ```
  (macOS BSD sed syntax. The `example.com` TLD is RFC 2606-reserved for documentation/test use.) Also scrub any unsubscribe links that embed the address as a query param.
- Tests should read directly from `samples/` — no separate `tests/fixtures/` needed.
- Watch out for: multipart messages where the HTML part isn't the first; messages with only a text/plain part (skip readability, just clean up); messages where `Date:` header is missing (fall back to IMAP-supplied internal date when available, else `None`).
- Timebox: the build-plan flags parsing as a "budget for it, but timebox to half a day" item (lines 98–99). Don't over-engineer.
