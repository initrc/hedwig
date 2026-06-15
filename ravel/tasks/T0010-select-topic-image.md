---
id: T0010
title: Select a representative image per topic
status: new
dependencies:
  - T0006
  - T0008
---

# Scope

- Add the image-selection step: for each topic (from T0008), gather the candidate images from the topic's
  source `Item`s and have the LLM pick the one image that actually illustrates the story (e.g. a benchmark
  chart) — or none. This filters logos/ads that survived the Day 1 dimension filter.
- The model selects from metadata only (alt text + dimensions); it does not fetch or view the image bytes.
- Output: per topic, the chosen `CandidateImage` or `None`.

# Acceptance

- A function takes a topic plus its candidate-image pool and returns the selected `CandidateImage` or `None`,
  using the T0006 structured-output helper.
- The selection is always one of the supplied candidates or null — the step never invents an image URL. Tests
  assert the returned image (when present) is identical to one of the inputs.
- "None" is a real outcome: when the pool is only logos/junk (or empty), the step returns `None` rather than
  forcing a pick.
- Tests run **without real API calls** (stub the LLM helper) and cover: picks a content image over a logo;
  returns `None` for an all-junk/empty pool; the chosen image is one of the candidates.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 step 4 (lines 127–130): pass the cluster's candidate
  images (alt text, dimensions) and have the LLM select which one illustrates the story, or none.
- Inputs: the topic's source `Item`s (via `Story.source_item_id` from T0007) and their
  `candidate_images: list[CandidateImage]` (`backend/app/ingest/parser.py:46`, fields `url`, `alt`, `width`,
  `height`). Suggested module: `backend/app/pipeline/image.py`.
- **Recover the pool, don't re-collect it.** Day 1 already gathered and junk-filtered candidate images on each
  `Item`; this step unions the candidates across the topic's source items and asks the model to choose. Do not
  re-parse HTML.
- **Selection by index, not by URL.** Send the model a numbered list of candidates (alt + dimensions) and have
  it return the chosen index or null; resolve the index back to the actual `CandidateImage` in code. This
  guarantees the output is always a real candidate and never a hallucinated URL. Validate the index is in
  range.
- **Schema shape:** an `output_format` model like `ImageChoice` with an optional `index: int | None`. Map
  `None`/out-of-range to "no image."
- This is intentionally a separate per-topic call from summarization (T0009) so each stage stays independently
  testable (build plan design rationale, lines 211–213). It depends on T0008 (needs clusters) but not on
  T0009 (does not need the summary text).
- Do not fetch image URLs to verify dimensions or content — that adds network flakiness; mirror the T0004
  decision to trust HTML-attribute metadata.
