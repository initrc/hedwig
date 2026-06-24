---
id: T0041
title: Improve RAG retrieval hit rate (three failure modes from the live baseline)
status: new
dependencies: []
---

# Scope

- The live `retrieval_hit_rate` aggregate is 0.500 (3/6 in-corpus questions
  retrieve a golden source). Three distinct failures, each a different mode:
  1. `/0` "Which new open-source LLMs were released this week?" expected
     `20260617-alpha-signal.eml` (GLM-5.2) and `20260618-alpha-signal.eml`;
     retrieved `20260618-superhuman.eml` only. The right chunk exists but ranked
     below an unrelated one — a ranking/relevance issue, not a missing chunk.
  2. `/3` "Where can I access Midjourney's body scanner?" **scoped to
     `topic_label="Midjourney body scanner"`** — retrieved `[]`. Scoped
     retrieval returned nothing, which points at a metadata mismatch: the
     stored `topic_label` in the Chroma index is almost certainly not the
     literal string `"Midjourney body scanner"`, so the `where` filter
     excludes every chunk.
  3. `/4` "Was there any AI company acquisition this week?" expected
     `20260617-superhuman.eml` (SpaceX-buys-Cursor, June 17) but retrieved
     `20260618-*` chunks. "This week" pulls newer chunks on top and buries the
     June-17 acquisition chunk that is the answer.
- Investigate each, fix what turns out to be a real retrieval bug, and raise
  the live `retrieval_hit_rate` toward 1.0. Some of these may be one fix
  (e.g. a better chunking strategy that lifts GLM-5.2 above OpenCut); others
  may be eval-fixture issues (e.g. an exact-`topic_label` filter that the
  index's free-form labels will never satisfy). Triage before fixing.

# Acceptance

- The live `retrieval_hit_rate` aggregate rises from the 0.500 baseline.
  Target ≥ 0.83 (5/6) unless a residual failure is documented as a genuine
  fixture/label mismatch the eval itself should be adjusted for (record which
  in findings).
- Each of the three documented failure modes is either resolved (the golden
  source is now retrieved) or explained with a recorded decision (e.g. "the
  topic-label filter is the wrong mechanism for free-form labels; switch to
  scoring-only retrieval and accept some loss of scope" or "fix the index to
  store the labeled `expected_topic` as `topic_label`").
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.
- Update `backend/evals/baselines/<date>-live.md` with the post-fix retrieval
  rows so the repo has an honest before/after.

# Implementation Notes

- Start from the three failing rows in
  `backend/evals/baselines/2026-06-23-live.md`. Reproduce each with a small
  ad-hoc script that embeds the question (`app.rag.embed.embed`) and searches
  the live Chroma store (`app.rag.chroma_store.ChromaStore`) with the same
  `where` clause `eval_retrieval_hit_rate` builds, then inspect the full
  top-k `ChunkResult`s (text + metadata + score) for that question. That will
  show whether the right chunk exists in the index at all, what its real
  `topic_label` metadata is, and what scores above it.
- The `/3` miss is almost certainly a `topic_label` metadata mismatch. The
  index is built in `app/rag/index.py`; check what `topic_label` it writes
  into `IndexChunk.metadata`. The eval's `topic_label=="Midjourney body
  scanner"` comes from `evals/fixtures/golden_qa.json` (a hand-picked string),
  while the index stores whatever the pipeline's `cluster()` step labeled the
  topic — free-form LLM text that won't match exactly. Either change the
  index to write a stable topic id, or change the eval to not hard-scope by
  hand-written labels (e.g. score the top-k across all topics and only treat
  the scope as a *preference*).
- The `/0` GLM-5.2 miss and the `/4` SpaceX-acquisition miss may relate to
  the chunking in `app/rag/chunk.py` or to the embedding's semantic preference
  for "current trend" prose over "X was released" prose. Don't speculate
  before the reproduce script shows the actual top-k.
- Watch the interaction with T0031's prior guardrail work — changing ranking
  or chunking may move the cosine-score distribution, which the 0.35
  threshold in `app/rag/ask.py` was calibrated against. Re-check refusal
  hit-rate (T0035) and answer_faithfulness after any retrieval change to avoid
  reintroducing refusal regressions.
- Out of scope: re-architecting retrieval (e.g. hybrid BM25 + vector), which
  is a bigger bet. Stay scoped to diagnosing and fixing these three failures.