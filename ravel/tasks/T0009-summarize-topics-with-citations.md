---
id: T0009
title: Summarize each topic with citations and action items
status: new
dependencies:
  - T0006
  - T0008
---

# Scope

- Add the per-topic summarization step: for each topic (from T0008), prompt the LLM to produce a tight
  summary that synthesizes across the topic's member stories, **with citations** back to which source
  newsletter each claim came from.
- In the same step, extract concrete **action items** — dated or actionable points (e.g. "NVDA reports Wed",
  "new model on HuggingFace"). The build plan allows this to be the same pass as summarization or a follow-up;
  do it in one call here.
- Output a structured per-topic result: `summary`, `sources` (citations to source items), and `action_items`.

# Acceptance

- A Pydantic model holds the per-topic output: `summary: str`, `sources` (references to the source `ParsedEmail`s
  backing the topic), and `action_items: list[...]`. It validates via Pydantic.
- A function summarizes a single topic (and a convenience over a list of topics), using the T0006
  structured-output helper.
- Citations resolve to real sources: every cited source maps to a `ParsedEmail` that actually contributed a story
  to the topic (recover via `Story.source_item_id`). Tests assert no citation points to an item outside the
  topic's stories.
- Tests run **without real API calls** (stub the LLM helper) and cover: a multi-source topic produces a
  summary plus ≥1 citation; action-item extraction returns a list (possibly empty) of the expected shape;
  citations are validated against the topic's source items.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 steps 2–3 (lines 119–126). The plan calls
  summarization "your core prompt-engineering surface — iterate on it" and is explicit that this is a
  **hand-write-it** learning step.
- Inputs: `Topic` from T0008 (`backend/app/pipeline/cluster.py`) and, transitively, the `Story` →
  `source_item_id` link from T0007 to resolve citations to `ParsedEmail`s. Suggested module:
  `backend/app/pipeline/summarize.py`.
- **Prompt design (the learning core):** pass the topic's stories with their source attribution and ask for
  (a) a synthesized summary that cites sources inline or by id, and (b) a list of action items. The skill of
  this task is iterating the prompt: run on one topic, inspect the JSON, fix faithfulness/citation issues,
  repeat.
- **Citations are the credibility surface.** Have the model cite by a stable source id you provide (the
  `ParsedEmail.id` of each contributing story's parent), then validate in code that returned citation ids are a
  subset of the topic's source items — reject hallucinated citations rather than trusting them. This same
  faithfulness check is what the Day 5 eval harness will score.
- **Reasoning depth:** summarization-with-synthesis benefits from more reasoning; consider raising Groq's
  `reasoning_effort` (exposed by the T0006 helper) for this call.
- Keep `sources`/`action_items` as typed sub-models (not bare strings where structure helps) so the Day 4
  detail panel and the Day 5 evals can read fields directly.
- This step does **not** pick an image — that is T0010, a separate per-topic call. Keep the two independently
  testable per the build plan's pipeline-stage design rationale (lines 211–213).
