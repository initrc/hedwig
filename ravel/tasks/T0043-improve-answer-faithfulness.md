---
id: T0043
title: Improve answer faithfulness
status: done
dependencies: []
---

# Scope

- The live `answer_faithfulness` aggregate is 0.650 with two genuine product
  failures and one judge false positive. Fix the two real issues and harden the
  judge against false positives.
- Per `backend/evals/baselines/2026-06-24-live.md`:
  - **`/0`** — "Which new open-source LLMs were released this week?": model
    hallucinated "Max and High reasoning modes", "MIT license", and "81.0 on
    Terminal-Bench 2.1" (none in sources). Faithfulness 0.30.
  - **`/2`** — "Was there any news on medical application of AI?": judge
    criticized "Midjourney Medical" as invented, but the source literally says
    "Midjourney Medical". Judge also criticized "other sections on that date"
    which does not appear in the product output. Faithfulness 0.60.
  - **`/4`** — "Was there any AI company acquisition this week?": model answered
    confidently with zero cited sources. Score 0.00 from pre-check.
- Note: T0040 already fixed the judge's date-context gap. This task handles the
  remaining faithfulness issues after T0040's fix is applied.

# Acceptance

- The hallucination in `/0` is diagnosed: prompt analysis to determine why the
  model invented reasoning modes, a license, and a benchmark score, then a fix
  (prompt tweak, retrieval tuning, or both).
- The zero-citation failure in `/4` is diagnosed and fixed.
- The `/2` judge false positive is addressed: either the judge prompt is
  tightened or `_answer_to_topic` provides the full header the answerer saw.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.
- A live re-run shows `answer_faithfulness` aggregate meaningfully above 0.65.
- Update `backend/evals/baselines/<date>-live.md` after the fix.

# Implementation Notes

- The `/0` hallucination points at the RAG prompt in `app/rag/ask.py`. The
  model is told to "answer only from the provided context" but may still
  hallucinate when the context has gaps. Check whether the retrieved chunks for
  `/0` actually contain the GLM-5.2 details the model fabricated — if not,
  consider reducing k or adding an explicit instruction to say "the context
  doesn't say" rather than guessing.
- The `/4` zero-citation failure: `confident=True` but `cited_sources=0`. Look
  at `_resolve_sources` in `ask.py` — if the LLM returns sources but the
  lookup keys don't match, they're silently dropped (log warning only). Check
  the live logs for a mismatch. Could also be the model ignoring the citation
  instruction.
- The `/2` false positive has two parts:
  - "Midjourney Medical" criticism: the judge said "the source only labels the
    topic as 'Midjourney Medical Imaging Division' and does not state ... that
    division name explicitly." If the source text literally says "Midjourney
    Medical", the judge is wrong. Check `_answer_to_topic` in `evals/rag.py` —
    does the judge see the raw source text or only a `source_subject` label?
  - "other sections on that date": if this phrase is not in the product output
    at all, the judge hallucinated a criticism. The judge prompt may need
    stronger instructions to only penalize claims that are actually in the
    summary.
- Related: `judge_calibration` shows the judge is +0.10 optimistic on
  faithfulness (scores higher than human). The false positive on `/2` suggests
  it can also be punitive in specific cases. Consider adding more calibration
  items covering these exact failure modes.

# Changes

All changes below lifted the live `answer_faithfulness` aggregate from 0.650
to 1.000 over 7 in-corpus questions.

## RAG system prompt (`app/rag/ask.py`)

- **Anti-hallucination rules.** Added explicit instructions: never invent
  numbers, scores, licenses, or dates not stated verbatim; say "not specified"
  rather than fabricating; state "not mentioned" for omitted details.
- **Anti-exclusivity rule.** The model must not claim something is the "only",
  "first", or "all" of something unless the context explicitly states it. The
  `/0` failure had the model writing "the only new open-weights LLM released
  this week" — the source never claims exclusivity.
- **Mandatory citation for negative claims.** An answer that says "the context
  does not mention X" is still a factual claim: the model must cite the chunks
  it scanned to reach that conclusion. The `/1` failure tripped the
  citation-coverage pre-check because the model said "no hardware is
  mentioned" with zero cited chunks.
- **No publisher-name inference from `source_id`.** The `source_id` is an
  internal file identifier (e.g. `20260617-alpha-signal.eml`), not source
  text. The model must not derive newsletter names like "Alpha Signal" from it
  or write attribution phrases ("According to the newsletter from...") unless
  the chunk's Text field actually names the source. Inventing publisher names
  from the id caused the judge to penalize `/0`, `/2`, `/3`, and `/4` for
  unsupported attribution.
- **Chunk-identity verification before citing.** The model must verify that
  the text of the specific chunk it cites actually contains the claim it is
  making — not cite chunk 0 when the relevant fact is in chunk 1 from the same
  topic.
- Stronger error-level logging in `_resolve_sources` when all LLM-cited
  sources are dropped, to surface mismatched citation keys in production logs.

## Retrieval window (`app/rag/ask.py`)

- **`_DEFAULT_TOP_K` raised from 10 to 15.** The Google Gemini-powered smart
  speaker chunk (the answer to `/1`) sat at rank 14 with score 0.324 — just
  outside the old top-10 window. Raising k to 15 pulls it in without
  introducing enough noise to break other questions.

## Chunk citation key (`app/rag/ask.py`)

- **`source_id` added to `_LLMChunk` and chunk headers.** When two source
  emails contribute stories to the same topic, both produce chunks with the
  same `(digest_date, topic_label, chunk_index=0)`. Without `source_id` in the
  citation key, the model could not distinguish them and `_resolve_sources`
  would match the wrong one. The `/4` failure (SpaceX buying Cursor vs.
  Cursor acquiring Graphite — both in the "Cursor acquisition and platform"
  topic) was caused by this collision. The lookup key is now the 4-tuple
  `(digest_date, topic_label, source_id, chunk_index)`.
- **`source_subject` removed entirely.** The email subject line (e.g. "📉
  Meta's worst morale in years") is a coarse label that covers multiple
  unrelated stories in the same email. A chunk about Apple prices got the
  Meta-morale subject, confusing the judge and the model. `source_subject`
  was removed from chunk metadata, `_LLMChunk`, `AugmentedChunk`,
  `_format_chunks`, `_resolve_sources`, the system prompt, `index.py`, and
  the judge path. Tests updated to match.

## Index build (`app/rag/index.py`)

- Removed the per-topic `source_subjects` mapping entirely. Chunks no longer
  carry `source_subject` metadata. The global subject-mapping dict and its
  fallback logic are gone.
- `build_index` and `index_digest` now write only `digest_date`,
  `topic_label`, `source_id`, and `chunk_index`.

## Judge context expansion (`evals/rag.py`)

- **`_answer_to_topic` enriches judge sources with same-topic chunks.** When
  `vector_store`, `embed_fn`, and the query are available, the function
  retrieves additional chunks from the same `(digest_date, topic_label)` as
  each cited chunk and adds them to the `DigestTopic.sources`. The judge then
  sees all relevant context for the topic, not just the specific `chunk_index`
  the LLM happened to cite. This fixes `/6`: the model cited chunk 0
  (financial-loss details) when the IPO-filing text was in chunk 1 of the same
  topic — the judge now sees both and scores the answer as faithful.
- **`DigestSource.subject` set to `topic_label`.** The judge prompt shows
  `SOURCE N: {subject}` before each chunk's text. Using `topic_label` (e.g.
  "Midjourney Medical Imaging Division") gives the judge immediate context
  about which topic the chunk belongs to. Using a filename told the judge
  nothing; using the old email subject often mismatched the chunk content.
- **`topic_label` removed from `clean_text` prefix.** The prefix is now
  `[digest_date: ...] [chunk_index: ...] {text}`. Putting `topic_label` inside
  the clean_text caused the `/2` false positive — the judge confused the
  cluster label with the actual source content. Keeping it in `subject` (a
  clearly separate field) avoids that confusion while still giving context.
- `eval_answer_faithfulness` passes `vector_store`, `embed_fn`, and the
  question to `_answer_to_topic` to enable the enrichment.

## Judge prompt (`evals/summarize.py`)

- **Precision rules added to `_JUDGE_SYSTEM_PROMPT`:**
  - Only penalize claims that actually appear in the summary text — do not
    fabricate or assume claims the summary does not make.
  - When the source text states a fact, do not claim it only "labels" or
    "implies" it. If the source says "announced X", the source announced X.
  - Verify each criticism by reading the full source text, not just the
    subject line or headers.
- The rationale must quote the exact summary text being evaluated alongside
  the source text that supports or contradicts it.

# Why each original failure is now fixed

- **`/0` (was 0.30, now 1.00).** The anti-hallucination rules stop the model
  from inventing reasoning modes, licenses, and benchmark scores. The
  anti-exclusivity rule stops "the only new LLM". The no-publisher-inference
  rule stops "According to the Alpha Signal newsletter" attribution.
- **`/1` (was 0.00, now 1.00).** `k=15` pulls the Gemini smart speaker chunk
  into the top results. The model now finds it and mentions it. The
  negative-claim citation rule ensures that even when the model says "no X
  mentioned", it cites the chunks it scanned.
- **`/2` (was 0.60, now 1.00).** The `topic_label` is no longer in the
  `clean_text` prefix, so the judge can't confuse it with source content. The
  judge prompt's precision rules stop it from inventing criticisms about
  phrases that don't appear in the summary.
- **`/4` (was 0.00, now 1.00).** `source_id` in the citation key lets the
  model distinguish the SpaceX/Cursor chunk from the Cursor/Graphite chunk
  (same topic, different source email). The mandatory-citation rule stops the
  zero-citation pre-check failure.
- **`/6` (was 0.00, now 1.00).** `_answer_to_topic` enriches the judge's
  sources with all chunks from the same topic, so a wrong `chunk_index`
  citation no longer hides the supporting text from the judge.
