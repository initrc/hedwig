---
id: T0011
title: Define the Digest schema and assemble the pipeline
status: new
dependencies:
  - T0007
  - T0008
  - T0009
  - T0010
---

# Scope

- Define the final `Digest` Pydantic schema and the orchestration that runs the full Day 2 batch core end to
  end: `ParsedEmail`s in → segment (T0007) → cluster (T0008) → summarize (T0009) → pick image
  (T0010) → one validated `Digest` out.
- Target schema: `{date, topics: [{label, summary, sources[], image}]}`. (The build plan also listed
  `action_items[]` per topic; that field was dropped in T0009 — see its Findings — so it is not in this schema.)
- Provide a single `run_pipeline(items: list[ParsedEmail], date=...) -> Digest` entry point that wires the stages
  together and assembles each topic's projection.

# Acceptance

- A `Digest` Pydantic model exists matching `{date, topics: [{label, summary, sources[], image}]}`, reusing
  the per-topic outputs from T0009 (summary/sources) and the selected image from T0010 (which may be null). It
  validates via Pydantic.
- A `run_pipeline(items, ...) -> Digest` function composes segment → cluster → summarize → image-select and
  returns one validated `Digest`; each topic in the result carries its label, summary, citations, and selected
  image (or null).
- Tests run **without real API calls** (stub each stage's LLM helper, or the stage functions) and verify the
  composition: a small set of `ParsedEmail`s flows through to a `Digest` with the expected topics, and every topic's
  `sources` resolve to input items. The assembled object round-trips through `model_dump(mode="json")` /
  re-validation.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 step 5 (lines 131–132) for the forced-JSON schema and
  Pydantic validation, plus the "agentic design ... pipeline ... structured/validated outputs at each step"
  rationale (lines 211–213).
- Inputs: `ParsedEmail` (`backend/app/ingest/parser.py:59`) and the four stage modules from T0007–T0010 under
  `backend/app/pipeline/`. Suggested module: `backend/app/pipeline/digest.py` for the `Digest` model and
  `run_pipeline`.
- **This task adds no new LLM prompt** — it composes the four existing stages and assembles their typed
  outputs. Keep the `Digest`'s per-topic shape a thin reuse of T0009's summary model + T0010's image, not a
  re-derivation. The card (Day 4) is a projection of a few fields; the detail panel needs the rest, so store
  the full per-topic structure.
- **Date handling:** default `date` to "today" but accept an override so a run is reproducible/testable. Match
  the project's existing tz-aware UTC convention (`_extract_received_at` in `parser.py:182` produces UTC).
- **Sources at the digest level:** each topic's `sources[]` should reference the contributing `ParsedEmail`s
  (resolved from `Story.source_item_id`), carrying enough for Day 4's "view original" link — e.g. the
  `ParsedEmail.id`, `source`/sender, `subject`, and `original_url` (`parser.py:68`).
- **Composition testing:** the cleanest seam is to stub each stage function (segment/cluster/summarize/
  image-select) so this task's tests assert wiring, not prompt behavior — the per-stage prompt behavior is
  already covered by T0007–T0010. No real API calls.
- T0006 is a transitive dependency (every stage uses the LLM helper) and is reached through T0007–T0010, so it
  is not listed here directly.
- Out of scope: persistence (T0012) and the HTTP endpoint (T0013). `run_pipeline` returns the `Digest`
  object; it does not write to a DB or touch FastAPI.

# Findings

- **"View original" opens the publisher's hosted page; we do not re-render the email.** Clicking a source's
  "view original" link opens `ParsedEmail.original_url` (the newsletter's own "view in browser" page) in a new
  tab. We deliberately do not render the email HTML ourselves: the parser keeps only `clean_text`, images, and
  `original_url` (not the raw HTML), and re-rendering third-party email HTML safely (stripping scripts and
  tracking pixels, fixing broken styling) is more work and risk than it earns for v1.
- **Fallback when `original_url` is `None`:** some emails have no "view in browser" link (or are plain-text),
  so show an in-app text view of the stored `clean_text` (plus the kept images) instead — our cleaned text, not
  the original HTML. This keeps the link from ever being dead.
- **What this means for the data carried:** the source projection must include `original_url`, and the digest
  must keep each source's `clean_text` reachable by id (so persistence in T0012 needs to store it too) so the
  fallback view has something to show.
