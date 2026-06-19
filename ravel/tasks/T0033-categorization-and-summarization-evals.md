---
id: T0033
title: Categorization and summarization evals
status: new
dependencies:
  - T0032
---

# Scope

- Build the categorization/summarization evals (build-plan Day 5 step 2):
  - **Topic-assignment accuracy** vs. the hand-labeled set: run the cluster step (T0008) on the
    labeled stories and score how well the predicted groupings match the labeled topics.
  - **Summary quality via LLM-as-judge** against a rubric: for each topic summary (T0009), have an
    LLM judge it for faithfulness (no invented facts, claims traceable to sources), conciseness, and
    coherence. Calibrate the judge against a few human scores so judge drift is visible.
- ~~**Image-selection relevance:** did the picker choose a relevant image vs. a logo?~~ **Dropped.**
  T0028 disabled topic image selection behind `_SELECT_TOPIC_IMAGES = False` and removed images from
  the frontend, so there is no selected image to score. Preserved here for traceability against the
  build plan; revisit only if T0028 is reverted.

# Acceptance

- A `eval_topic_assignment(stories, labels, *, client=None) -> list[EvalResult]` function runs the
  T0008 `cluster()` step on the labeled stories and scores the predicted grouping against the
  hand-labeled expected topics. The metric is **story co-membership**, not exact label string match
  (LLM labels are free-form): stories the human placed in one topic should land in a single predicted
  topic, and stories in different human topics should not be merged. The chosen metric is named and
  documented in a comment.
- A `eval_summary_quality(digest, *, judge_client=None) -> list[EvalResult]` function runs an
  LLM-as-judge over each topic's summary against a rubric (faithfulness / conciseness / coherence)
  and returns one `EvalResult` per topic plus an aggregate. The judge is a structured LLM call
  (`parse_structured` from T0006) returning per-dimension scores.
- **Judge calibration:** a small set of summaries (3–5) is hand-scored by a human against the same
  rubric, and the judge's scores on the same summaries are recorded alongside. The delta (judge
  drift) is reported as an `EvalResult` so the scorecard shows whether the judge is biased high/low,
  not just the raw scores.
- Tests run **without real API calls** — stub `cluster`'s LLM (`client=`) and the judge LLM
  (`judge_client=`) and assert: the topic-assignment metric scores a perfect grouping at 1.0 and a
  shuffled grouping below 1.0; the judge aggregation turns structured judge output into the right
  `EvalResult`s; calibration delta is computed correctly from a hand-scored fixture.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 2 (lines 201–205): "Topic-assignment
  accuracy vs. your labels. Summary quality via LLM-as-judge against a rubric (faithful to sources?
  no invented facts? concise?). Calibrate the judge against a few of your own human scores so you
  understand judge drift." The plan marks the eval scoring logic as **hand-write-it** learning core
  (lines 66–67) — iterate the judge prompt like you iterate the summarize prompt.
- **Topic-assignment metric (hand-write this):** because cluster labels are LLM-generated strings,
  comparing them by equality is meaningless. Score by membership: two stories the human put in one
  topic should share a predicted topic, and stories in different human topics should split. A simple,
  explainable choice is pairwise accuracy over story pairs — "for each pair of stories the human
  co-grouped, did the model co-group them too?" Document the formula in the module docstring. Avoid
  pulling in scikit-learn for one metric; if you use adjusted Rand index, justify it. The point is a
  number you can defend, not a library call.
- **Inputs:** the labeled stories come from T0032's `dataset.py`. For the topic-assignment eval,
  reconstruct the `Story` objects the clusterer expects (`backend/app/pipeline/segment.py`) from the
  fixture (the fixture carries `source_item_id`, `title`, `text`). For the summary-quality eval, run
  the real summarize step on the predicted topics (or load a persisted `Digest` from the T0012 store
  via `DigestStore.list_recent`, `backend/app/storage/digest_store.py:151`) and judge its
  `DigestTopic.summary` + `sources`.
- **LLM-as-judge design (the learning core):**
  - Reuse `parse_structured` from `backend/app/llm/client.py:111` with a Pydantic rubric schema
    (e.g. `RubricScore(faithfulness: float, conciseness: float, coherence: float, rationale: str)`).
  - The judge prompt gives the topic's stories (source text) and the summary, and asks: is every
    claim in the summary supported by the source text? Is anything invented? Is it concise? Score
    each dimension 0.0–1.0. Iterate this prompt — judge drift is the thing this task teaches you to
    see, so do not skip the calibration step.
  - Faithfulness is the dimension that matters most (it is the same property T0009's citation
    check enforces in code); weight the aggregate toward it and document the weighting.
- **Calibration:** hand-score 3–5 summaries on the same rubric (record the scores in a fixture under
  `backend/evals/fixtures/`, e.g. `judge_calibration.json`). Run the judge on the same summaries and
  emit an `EvalResult` whose `detail` states the mean per-dimension delta (judge minus human). This
  is what "understand judge drift" (build-plan line 204) means in practice — a number on the
  scorecard, not a vibe.
- **Citation faithfulness is already partly checked in code** (`_resolve_sources` in
  `backend/app/pipeline/summarize.py:85` drops invented source ids). The judge evaluates a stronger
  property: that the summary's *textual claims* are backed by the cited sources, not just that the
  cited ids are valid. Don't conflate the two — the code check is id validity, the judge is claim
  support.
- **Cost guard:** the judge is an extra LLM call per topic. Judge only the topics in the labeled set
  (a handful), not every digest ever produced. The runner (T0037) gates real calls behind a
  `--live`/env flag; respect that here by taking `judge_client=None` (default client) and letting
  tests inject a fake.
- **Image-selection sub-item:** dropped per T0028. `DigestTopic.image` is always `null` with
  `_SELECT_TOPIC_IMAGES = False` (`backend/app/pipeline/digest.py`), so there is no selection to
  score. Do not write an image-relevance eval. If T0028 is ever reverted, add the eval then; the
  build-plan line 205 reference is left struck through above for traceability (same pattern T0009
  used for action items).
- **Out of scope:** the runner and markdown scorecard (T0037), prompt-version comparison (T0036,
  which reuses `eval_summary_quality`), RAG evals (T0034), and safety probes (T0035).
