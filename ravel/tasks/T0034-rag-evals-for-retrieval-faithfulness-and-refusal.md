---
id: T0034
title: RAG evals for retrieval, faithfulness, and refusal
status: done
dependencies:
  - T0032
---

# Scope

- Build the RAG evals (build-plan Day 5 step 3) over the golden Q&A set from T0032:
  - **Retrieval hit rate:** for each in-corpus question, did the right source come back in the
    top-k retrieved chunks?
  - **Answer faithfulness:** does the generated answer stick to the retrieved sources (no
    hallucination, claims supported by cited chunks)?
  - **Low-confidence refusal:** does the guardrail fire (`confident=False`, no LLM call) on the
    out-of-corpus questions in the golden set?

# Acceptance

- A `eval_retrieval_hit_rate(questions, *, vector_store, embed_fn, k=5) -> list[EvalResult]`
  function runs retrieval for each golden question (without necessarily calling the LLM — retrieval
  is the `embed` + `vector_store.search` half of `ask()`) and scores whether each question's
  `expected_source_ids` appear in the top-k results. One `EvalResult` per question plus an aggregate
  hit-rate `EvalResult`.
- A `eval_answer_faithfulness(questions, *, vector_store, embed_fn, client=None, judge_client=None)
  -> list[EvalResult]` function runs the full `ask()` and scores the answer's faithfulness — either
  via the LLM-as-judge from T0033 (reuse the judge + rubric) or a citation-coverage check ("every
  claim in the answer is supported by a cited chunk's text"). The chosen approach is documented.
- A `eval_refusal(questions, *, vector_store, embed_fn) -> list[EvalResult]` function runs `ask()`
  on the out-of-corpus questions and asserts `confident=False` with no LLM call made. The
  "no LLM call" assertion is verified by injecting a client whose call counter stays at zero.
- Tests run **without real API calls** — use the `StubStore` and fakes from
  `backend/tests/rag/fakes.py` and the `FakeClient` pattern from `backend/tests/fakes.py`. Cover: a
  question whose golden source is in the stub store scores a hit; a question with no matching chunk
  scores a miss; an out-of-corpus question (stub store returns low scores) returns `confident=False`
  and the LLM client is never called.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 3 (lines 206–208): "RAG evals:
  retrieval hit rate (did the right source come back?), answer faithfulness, and does the
  low-confidence refusal fire on out-of-corpus questions?"
- **Reuse the real entry point.** Score `ask()` from `backend/app/rag/ask.py:112` — the same
  function the `/chat` endpoints (T0016) call — not a re-implementation. Inject `vector_store`,
  `embed_fn`, and `client` exactly as the chat tests do, so the eval measures the real retrieval +
  generation path. This is the decoupling-for-testability rationale (build-plan lines 234–236)
  paying off twice: the same seams that made T0015 testable make it evaluable.
- **Retrieval hit rate (no LLM needed):** the golden Q&A fixture (T0032) lists
  `expected_source_ids` per question. Run `embed_fn([query])` then
  `vector_store.search(query_vector, k=k, where=...)` and check whether any returned
  `ChunkResult.metadata["source_id"]` is in `expected_source_ids`. Scoring retrieval without the LLM
  call keeps this eval cheap and isolates the retrieval quality (chunking/embedding from T0014,
  threshold from T0031) from the generation quality.
- **Answer faithfulness:** prefer reusing T0033's LLM-as-judge rather than writing a second judge —
  same rubric (faithfulness / conciseness / coherence), now applied to the RAG answer with the
  retrieved chunks as the "source text." If a separate citation-coverage check is added (does every
  `AugmentedChunk` the answer cites actually support the claims?), keep it as a cheap deterministic
  pre-check before the judge. Document which path the aggregate score uses.
- **Refusal path:** `ask()` short-circuits at `backend/app/rag/ask.py:147`
  (`results[0].score < _CONFIDENCE_THRESHOLD`) and returns `confident=False` with no LLM call. The
  eval asserts both: the `AugmentedAnswer.confident` flag is `False`, **and** the injected
  `FakeClient.call_count == 0` (the guardrail must not have fallen through to generation). The
  `_CONFIDENCE_THRESHOLD` was calibrated in T0031 (0.35, with the comment at `ask.py:30` recording
  the empirical range); the out-of-corpus questions in the golden set should sit well below it.
- **Stub store scores:** to test the refusal path deterministically, the `StubStore` in
  `backend/tests/rag/fakes.py` needs to return chunks with controllable scores — add a way to seed
  low-scoring chunks for out-of-corpus queries if it doesn't already exist, rather than relying on
  the real embedding distance. The hit-rate test seeds chunks whose `source_id` matches the golden
  expectation; the refusal test seeds chunks scoring below the threshold.
- **Scoped retrieval:** the golden Q&A fixture may set `scope` (a `topic_label`) for some questions.
  When set, pass `topic_label=scope` to `ask()`/`search` so the eval also covers the per-topic scoped
  path (the detail-panel chat from Day 4). One aggregate hit rate across scoped + global questions
  is fine; note the split in `detail` if a scoped question fails.
- **Out of scope:** the runner/scorecard (T0037), the categorization evals (T0033), and safety
  probes (T0035). This task scores the RAG path only.
