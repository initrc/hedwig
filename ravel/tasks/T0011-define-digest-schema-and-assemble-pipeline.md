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
  end: `ParsedEmail`s in → segment (T0007) → cluster (T0008) → summarize + action items (T0009) → pick image
  (T0010) → one validated `Digest` out.
- Target schema (from the build plan): `{date, topics: [{label, summary, sources[], action_items[], image}]}`.
- Provide a single `run_pipeline(items: list[ParsedEmail], date=...) -> Digest` entry point that wires the stages
  together and assembles each topic's projection.

# Acceptance

- A `Digest` Pydantic model exists matching `{date, topics: [{label, summary, sources[], action_items[],
  image}]}`, reusing the per-topic outputs from T0009 (summary/sources/action_items) and the selected image
  from T0010 (which may be null). It validates via Pydantic.
- A `run_pipeline(items, ...) -> Digest` function composes segment → cluster → summarize → image-select and
  returns one validated `Digest`; each topic in the result carries its label, summary, citations, action
  items, and selected image (or null).
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
