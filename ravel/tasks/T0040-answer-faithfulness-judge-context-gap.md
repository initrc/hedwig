---
id: T0040
title: Give the answer-faithfulness judge the same context the answerer had
status: done
dependencies: []
---

# Scope

- The live `answer_faithfulness` score (0.317) is systematically depressed by
  an eval-design gap, not a model failure: the `ask()` answerer is shown each
  retrieved chunk's full header block — `digest_date`, `topic_label`,
  `source_subject`, `chunk_index`, then the chunk text — and faithfully uses
  that metadata in its answer (e.g. "According to the 2026-06-18 Superhuman...").
  But `eval_answer_faithfulness` builds the judge's `DigestTopic` from
  `chunk.text` and `chunk.source_subject` only (via `_answer_to_topic` in
  `evals/rag.py`), so the judge never sees the `digest_date` the model was
  shown. The live judge then penalizes the answer for "inventing a specific
  date that does not appear in any source" — across `/1`, `/2`, and `/5` — when
  the date did appear, in the header the judge was not given.
- Fix the asymmetry so the judge and the answerer operate on the same context.
  The narrow fix is to include the chunk's `digest_date` (and the other header
  fields `ask()` shows the model) in the `DigestSource` the judge reads, so a
  faithful restatement of header metadata is no longer scored as a
  hallucination.

# Acceptance

- After the fix, the live `answer_faithfulness` per-question rationales no
  longer cite "invents a specific date 'June 18, 2026'" as a faithfulness
  deduction for answers that correctly attribute the chunk's `digest_date`.
- The judge prompt still penalizes genuinely invented facts — a date the
  model made up that is in neither the header nor the chunk body should still
  score low. The fix widens the judge's ground truth to "header + body"; it does
  not lower the faithfulness bar.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass. Existing
  `tests/evals/test_rag.py` tests continue to pass; if any asserted on the
  exact shape of `_answer_to_topic`'s output, update them in lockstep and note
  the change in the task findings.
- Re-run `uv run python evals/run.py --live` and update
  `backend/evals/baselines/<date>-live.md` with the post-fix score so the repo
  reflects the corrected measurement.

# Implementation Notes

- `_answer_to_topic` in `backend/evals/rag.py` is the single function that maps
  an `ask()` answer's `AugmentedChunk`s into the `DigestSource`s the judge
  reads. It currently sets `subject=chunk.source_subject` and
  `clean_text=chunk.text`. The `AugmentedChunk` model (`app/rag/ask.py`) also
  carries `digest_date`, `topic_label`, `source_id`, and `chunk_index` — every
  header field `ask()._format_chunks` puts in the prompt. The fix is to make
  the header information visible to the judge alongside the chunk text.
- Two reasonable shapes, pick one and record it in findings:
  1. Prepend a short header line to the `clean_text` given to the judge, e.g.
     `f"[digest_date: {chunk.digest_date}] [topic: {chunk.topic_label}] {chunk.text}"`
     so the judge sees the metadata inline with the body.
  2. Map the header fields onto the existing `DigestSource` shape in a way the
     `_judge_user_prompt` (in `evals/summarize.py`) surfaces — but note the
     judge prompt builds a "SOURCE N: {subject}\n{clean_text}" block, so option
     (1) is simpler and avoids teaching the judge prompt about new fields.
- Consider whether the same asymmetry affects any other field. The answerer
  also sees `topic_label`, `chunk_index`, and `source_subject` in the header;
  `source_subject` is already given to the judge (as `subject`), so
  `digest_date` is the demonstrated miss. Including the full header
  (date + topic + subject + index) in the judge's view is the safe
  generalization; if you trim, keep at least `digest_date` and `source_subject`.
- This is an eval-design fix in T0034's territory; it does not touch
  `app/rag/ask.py` (the answerer is doing the right thing) or the judge prompt
  itself (`evals/summarize._JUDGE_SYSTEM_PROMPT`).
- Out of scope: re-judging deeper model tendencies (e.g. real hallucinations
  beyond the date issue). After this fix they become visible — file a follow-up
  if a live re-run shows a separate residual hallucination pattern.