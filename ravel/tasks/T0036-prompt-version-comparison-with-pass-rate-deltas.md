---
id: T0036
title: Prompt-version comparison with pass-rate deltas
status: new
dependencies:
  - T0033
---

# Scope

- Build the prompt-version comparison (build-plan Day 5 step 5): treat prompts as versioned
  artifacts and run the summarization eval suite (T0033) against two versions of the summarization
  prompt, showing the per-version pass rates and the delta between them — prompts under regression
  testing, not edited blindly.
- Make the summarization prompt swappable so the comparison can run both versions without forking the
  pipeline: introduce a small prompt registry (or a prompt-override parameter) so v1 and v2 are
  first-class, named artifacts rather than edits to a hardcoded constant.

# Acceptance

- Two versioned summarization prompts exist (v1 = the current `_SYSTEM_PROMPT` in
  `backend/app/pipeline/summarize.py:58`, v2 = a deliberate variant). Both are named, stored as
  artifacts (e.g. in a `backend/evals/prompts/` or `backend/app/pipeline/prompts.py` registry), and
  selectable by name.
- `summarize_topic` (and `summarize_topics`) can run with either prompt version without changing its
  public signature's callers — e.g. an optional `prompt_version: str = "v1"` parameter or a
  prompt-registry lookup. The default remains v1 so existing behavior and tests are unchanged.
- A `eval_prompt_comparison(stories, labels, *, client=None, judge_client=None) -> list[EvalResult]`
  function runs T0033's `eval_summary_quality` under v1 and under v2 on the same labeled set, then
  emits `EvalResult`s for each version's aggregate score plus an `EvalResult` whose `detail` states
  the pass-rate delta (v2 minus v1, per rubric dimension and overall).
- Tests run **without real API calls** — stub both the summarize LLM and the judge LLM, feed
  deterministic summaries/scores for each version, and assert the comparison computes the right
  deltas and picks the higher-scoring version correctly. No real API calls.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 5 (lines 211–212): "Prompt-version
  comparison: run the suite against two versions of your summarization prompt and show pass-rate
  deltas — prompts treated as versioned artifacts with regression testing." Also the design
  rationale "prompts are versioned and run through a regression suite" (line 239).
- **The prompt is the thing being regressed.** The summarization prompt
  (`backend/app/pipeline/summarize.py:58`) is the build-plan's "core prompt-engineering surface"
  (Day 2, line 121). This task turns edits to it from "I changed it and it looks fine" into "v2
  scored +0.08 on faithfulness and −0.03 on conciseness vs v1" — the regression mechanism the whole
  eval harness exists to provide.
- **Making the prompt swappable:** prefer a small prompt registry (`backend/app/pipeline/prompts.py`
  or `backend/evals/prompts/`) over scattering `if version == "v2"` checks in `summarize.py`. A
  `dict[str, str]` keyed by version name, looked up by `summarize_topic`, keeps the prompt text
  first-class and readable. The build plan calls prompts "versioned artifacts," so they should live
  as named artifacts, not inline string edits. Default lookup is v1 (the current text, verbatim) so
  nothing about the production pipeline changes unless a caller opts in.
- **v2 is a deliberate variant, not necessarily better.** The point is to demonstrate the
  regression mechanism, not to ship an improved prompt. Good v2 candidates: instruct the model to be
  more concise (a length constraint), or to cite inline by newsletter name in addition to id, or to
  explicitly ignore boilerplate/sponsor text. Choose one, name it, and record in the task findings
  what v2 changed and what the delta came out to (once the live run is done).
- **Reuse, don't re-derive.** `eval_prompt_comparison` calls `eval_summary_quality` from T0033 twice
  — once per prompt version — on the *same* labeled stories, then computes the delta. Do not write a
  second judge or a second summary-quality scorer; the comparison is an orchestration over T0033's
  existing eval, exactly as T0011 orchestrated T0007–T0010 without re-implementing them.
- **Same labeled set, same judge.** Both versions must be scored against the same hand-labeled
  ground truth and the same judge prompt, so the only variable is the summarization prompt. If the
  judge is non-deterministic, note it and consider averaging a couple of judge runs per version;
  record the decision in the module docstring.
- **Cost:** this doubles the summarize + judge LLM calls for the labeled set. Keep the labeled set
  small (T0032's ~30–50 stories → a handful of topics) and rely on the runner's `--live`/env gate
  (T0037) so the comparison doesn't run on every CI pass.
- **Out of scope:** comparing prompts for other stages (cluster, RAG) — the build plan scopes this
  to the summarization prompt; the same mechanism generalizes later. The runner and scorecard are
  T0037.
