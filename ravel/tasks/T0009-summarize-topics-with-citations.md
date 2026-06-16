---
id: T0009
title: Summarize each topic with citations
status: done
dependencies:
  - T0006
  - T0008
---

# Scope

- Add the per-topic summarization step: for each topic (from T0008), prompt the LLM to produce a tight
  summary that synthesizes across the topic's member stories, **with citations** back to which source
  newsletter each claim came from.
- Output a structured per-topic result: `summary` and `sources` (citations to source items).
- **Action items dropped (see Findings).** The build plan originally bundled action-item extraction into this
  step; reading the real `backend/samples/` newsletters showed it produces no useful items for our sources, so
  it was cut. The original action-item scope is preserved below struck through for traceability:
  - ~~In the same step, extract concrete action items — dated or actionable points (e.g. "NVDA reports Wed",
    "new model on HuggingFace"), output as `action_items`.~~

# Acceptance

- A Pydantic model holds the per-topic output: `summary: str` and `sources` (references to the source
  `ParsedEmail`s backing the topic). It validates via Pydantic.
- A function summarizes a single topic (and a convenience over a list of topics), using the T0006
  structured-output helper.
- Citations resolve to real sources: every cited source maps to a `ParsedEmail` that actually contributed a story
  to the topic (recover via `Story.source_item_id`). Tests assert no citation points to an item outside the
  topic's stories.
- Tests run **without real API calls** (stub the LLM helper) and cover: a multi-source topic produces a
  summary plus ≥1 citation; citations are validated against the topic's source items.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 steps 2–3 (lines 119–126). The plan calls
  summarization "your core prompt-engineering surface — iterate on it" and is explicit that this is a
  **hand-write-it** learning step.
- Inputs: `Topic` from T0008 (`backend/app/pipeline/cluster.py`) and, transitively, the `Story` →
  `source_item_id` link from T0007 to resolve citations to `ParsedEmail`s. Suggested module:
  `backend/app/pipeline/summarize.py`.
- **Prompt design (the learning core):** pass the topic's stories with their source attribution and ask for a
  synthesized summary that cites sources by id. The skill of this task is iterating the prompt: run on one
  topic, inspect the JSON, fix faithfulness/citation issues, repeat.
- **Citations are the credibility surface.** Have the model cite by a stable source id you provide (the
  `ParsedEmail.id` of each contributing story's parent), then validate in code that returned citation ids are a
  subset of the topic's source items — reject hallucinated citations rather than trusting them. This same
  faithfulness check is what the Day 5 eval harness will score.
- **Reasoning depth:** summarization-with-synthesis benefits from more reasoning; consider raising Groq's
  `reasoning_effort` (exposed by the T0006 helper) for this call.
- Keep `sources` as a typed sub-model (not bare strings) so the Day 4 detail panel and the Day 5 evals can
  read fields directly.
- This step does **not** pick an image — that is T0010, a separate per-topic call. Keep the two independently
  testable per the build plan's pipeline-stage design rationale (lines 211–213).

# Findings

- **Action items were cut after inspecting real samples.** The build plan (Day 2 step 3) and the original
  scope of this task called for extracting `action_items` — "dated or actionable points." Reading the real
  newsletters in `backend/samples/` (a finance recap, `*-tikr.eml`, and an AI-news digest, `*-alpha-signal.eml`)
  showed every candidate action item was one of: (a) a "watch" event that merely restates the summary (e.g.
  "Lululemon reports Thursday" from TIKR's "Week Ahead"); (b) a "go try this" item a reader won't act on
  mid-digest (e.g. "Claude Fable 5 available now"); or (c) a date pulled from a sponsor ad, which segmentation
  already discards. None was a genuine, distinct-from-the-summary action for our two source types, so the field
  earned no place and was removed (models, prompt, tests). Revisit only if a source that actually carries
  to-dos (deadlines, RSVPs) is added.
- **Downstream references were propagated with this task.** `ravel/tasks/T0011` (target schema and
  acceptance) and `ravel/docs/build-plan.md` (the "what it does" intro, the architecture diagram, Day 2 step 3,
  the Day 2 step 5 schema, and the Day 4 detail-sheet list) all had `action_items` removed. The build plan's
  Day 2 step numbering was deliberately left intact (step 3 now reads "dropped") so other tasks' "Day 2 step N"
  references still resolve.
