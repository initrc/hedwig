---
id: T0007
title: Segment newsletters into per-story sub-items
status: new
dependencies:
  - T0006
---

# Scope

- Add an LLM step that splits each parsed newsletter `Item` into one or more per-story `Story` sub-items
  *before* clustering. This resolves the granularity question raised in T0004 and flagged in the build plan:
  Day 1 produces one `Item` per *email*, but a single newsletter usually bundles many distinct stories, so
  clustering whole emails is too coarse.
- A `Story` carries enough to be clustered and summarized downstream: a short title, the story's text (a
  slice/synthesis of the parent's `clean_text`), and a back-reference to its source `Item` (so citations and
  the candidate-image pool can be recovered later).
- Provide a function that takes a list of `Item`s and returns a flat list of `Story`s (each email may yield
  several).

# Acceptance

- A `Story` Pydantic model exists with at least: a stable `id`, `source_item_id` (the parent `Item.id`), a
  `title`, and `text`. It validates via Pydantic.
- A `segment(item: Item) -> list[Story]` (and a list-level convenience over many items) exists; each returned
  `Story.source_item_id` matches a real input `Item.id`.
- The step uses the T0006 structured-output helper with a Pydantic schema — no hand-rolled JSON parsing.
- A newsletter that genuinely contains one story yields exactly one `Story`; a multi-story newsletter yields
  several. (Verify against the committed `backend/samples/*.eml` corpus, which is real multi-story
  newsletters.)
- Tests run **without real API calls** (stub the LLM helper, as established in T0006) and cover: a
  single-story item → one story; a multi-story item → many stories; every story's `source_item_id` is valid.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 step 1 and the per-story segmentation note
  (lines 110–118), which explicitly says to "decide the item granularity (email vs. story) when writing
  the Day 2 tasks." This task makes that decision: **story granularity**, via a dedicated segmentation
  step that is its own LLM call.
- Input type: `Item` from `backend/app/ingest/parser.py:59` (fields: `id`, `source`, `subject`,
  `received_at`, `clean_text`, `candidate_images`, `original_url`). Suggested new module:
  `backend/app/pipeline/segment.py` (a new `app.pipeline` package for the Day 2 batch core).
- **Prompt design (the learning core — hand-write this):** feed the model the `subject` + `clean_text` and
  ask it to return a list of stories, each with a tight title and the relevant text. The build plan's
  guidance is to write the prompt by hand, get it working on one newsletter, inspect the JSON, then iterate.
- **Schema shape for `parse`:** the model returns a list, but `output_format` expects a single object — wrap
  it (e.g. a `Segmentation` model with a `stories: list[StorySpec]` field) and map to `Story` instances,
  filling `source_item_id` and a generated `id` in code (don't trust the LLM to mint stable ids). A simple
  `f"{item.id}#{index}"` id keeps stories traceable to their email.
- **Do not** pass `candidate_images` into the segmentation prompt — image selection is a separate step
  (T0010) that works per-topic. Stories only need to reference the parent `Item.id`; the image pool is
  recovered from the parent at selection time.
- Edge cases: an `Item` with empty `clean_text` should yield zero stories (or one trivially), not crash;
  keep titles short and free of trailing newsletter boilerplate.
