---
id: T0032
title: Build labeled eval set and harness scaffolding
status: new
dependencies: []
---

# Scope

- Build the labeled eval set the rest of Day 5 scores against (build-plan Day 5 step 1): hand-label
  ~30–50 items with the correct topic/category for each segmented story, plus a golden Q&A set for
  the RAG side (question → which source should answer it, and out-of-corpus questions that the
  guardrail should refuse).
- Stand up the `backend/evals/` package: a loader that reads the labeled fixtures into typed models,
  and the shared result schema (`EvalResult` / `Scorecard`) that the per-eval tasks (T0033–T0036)
  emit and the runner (T0037) aggregates into a scorecard.

# Acceptance

- JSON fixtures live under `backend/evals/fixtures/` and split into two labeled sets:
  - A **topic-labeling set**: each entry is a segmented `Story` (or enough of one to reproduce the
    cluster input — `source_item_id`, `title`, `text` snippet) plus the hand-labeled expected
    topic/category it belongs to. ~30–50 stories total, drawn from the real `backend/samples/*.eml`.
  - A **golden RAG Q&A set**: each entry is `{question, expected_source_ids[], scope?, expect_refusal}`.
    In-corpus questions name the `ParsedEmail.id`(s) that should answer them; out-of-corpus questions
    (weather, recipes, car prices) set `expect_refusal: true`.
- A loader (`backend/evals/dataset.py` or similar) reads the fixtures into Pydantic models and
  validates them (no malformed fixture silently passes).
- A shared result schema is defined in `backend/evals/types.py`: at minimum
  `EvalResult(name: str, passed: bool, score: float, detail: str)` and
  `Scorecard(results: list[EvalResult], summary: str)`. Every eval function in T0033–T0036 returns
  `list[EvalResult]`; T0037 builds the `Scorecard`.
- Tests for the loader and the schema live in `backend/tests/evals/` and run **without real API
  calls** — they cover fixture round-tripping, validation errors on bad fixtures, and the
  result/schema models.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 1 (lines 199–200) and step 6 (line 213,
  the shared results surface the runner renders). The plan is explicit that the eval harness is the
  most valuable part of the build ("Protect time for it — it's Day 5 and it must not get cut",
  lines 16–17).
- **The labeled set is hand-labeled data, not code to delegate.** The human work is reading the real
  newsletters in `backend/samples/` (five `.eml` files across 2026-06-17 and 2026-06-18: AlphaSignal,
  Superhuman, TIKR), running them through the Day 1–2 pipeline mentally (or via a one-off script) to
  get the segmented `Story` list, and assigning each story its true topic. The loader is the code;
  the labels are the substance.
- **Where the labels come from:** segmentation is T0007 (`backend/app/pipeline/segment.py`), stories
  carry `source_item_id` (= `ParsedEmail.id`, set in `backend/app/ingest/parser.py:59`). The expected
  topic is a free-form short label you choose by hand — it does not need to match the LLM's wording,
  since T0033 scores topic assignment by story co-membership, not exact label string match (see
  T0033). Keep labels stable once written; they are the ground truth the suite regresses against.
- **Golden Q&A source ids:** `ParsedEmail.id` is the message id / derived id from parsing. For
  in-corpus questions, list the id(s) whose `clean_text` actually contains the answer. For scoped
  questions, optionally record the `topic_label` to test scoped retrieval. Out-of-corpus questions
  are the refusal-path probes (also reused by T0034's refusal eval).
- **Package layout** (mirrors the `backend/app/rag/` split in T0014 — thin `__init__`, one concern
  per module):
  - `backend/evals/__init__.py` — docstring only, no facade.
  - `backend/evals/types.py` — `EvalResult`, `Scorecard` (and any small enums like a pass/fail
    reason) shared across T0033–T0037.
  - `backend/evals/dataset.py` — the fixture loader + the Pydantic models for the labeled sets
    (`LabeledStory`, `GoldenQA`).
  - `backend/evals/fixtures/topic_labels.json` and `backend/evals/fixtures/golden_qa.json`.
  - The per-eval modules (`categorize.py`, `rag.py`, `safety.py`, `compare.py`) and `run.py` land in
    T0033–T0037; this task only builds the foundation they all import from.
- **Result schema design:** keep `EvalResult` flat and serializable so T0037 can render it as
  markdown without per-eval special-casing. `score` is a 0.0–1.0 fraction (e.g. hit rate, judge
  rubric average) so the scorecard can average across evals of different sizes. `detail` holds a
  short human-readable note (e.g. "3/5 golden sources retrieved", "judge drift +0.1 vs human"). Do
  not bake per-eval shapes into `EvalResult` — push specifics into `detail`.
- **Test strategy:** load the real fixtures and assert counts/types; add a deliberately-bad fixture
  (e.g. a `GoldenQA` missing `question`) and assert the loader raises. Do not construct digests or
  call the LLM here — that is T0033's job. Reuse `backend/tests/fakes.py` patterns only if a fixture
  needs a `ParsedEmail`/`Story` shape.
- **Out of scope:** the eval functions themselves (T0033–T0036), the runner and markdown rendering
  (T0037), and any live LLM/embedding calls. This task is data + types + a loader.
