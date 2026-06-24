---
id: T0042
title: Revisit the refusal golden label for the OpenAI IPO question
status: new
dependencies: []
---

# Scope

- The live `refusal` row for "What's the rumored IPO date of OpenAI?" was
  scored `fail` because `ask()` did not refuse: `confident=True`,
  `llm_calls=1`. Retrieval cleared the 0.35 guardrail because the archive
  *does* contain an OpenAI-IPO-adjacent story — the "OpenAI lost $38.5B in
  2025 / filed confidentially to go public" item in
  `20260617-superhuman.eml`. The model answered from it.
- That makes the `expect_refusal=True` label on this question wrong for an
  archive that genuinely contains OpenAI-IPO-adjacent news. The eval flagged
  the mismatch correctly; the fix is to decide whether (a) the question is
  in-corpus and should be labeled with `expected_source_ids` pointing at the
  OpenAI-loss story (the model was right to answer), or (b) the question is
  genuinely out-of-corpus — "the archive says nothing about an IPO *date*" —
  and the threshold needs to be more specific so a related-but-not-dating
  chunk does not clear it.

# Acceptance

- One of:
  - The `golden_qa.json` entry for "What's the rumored IPO date of OpenAI?"
    flips to `expect_refusal=False` with the right `expected_source_ids`
    (and the live `refusal` row then passes because there is no out-of-corpus
    expectation on a question the archive answers), or
  - The refusal path is taught to distinguish "archive discusses X" from
    "archive answers the specific ask about X" (e.g. a higher or
    per-question-type threshold) and the live `refusal` row passes for the
    right reason.
- The decision is recorded in the task findings with the reasoning, so a
  future reader knows whether the label changed or the mechanism did.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass. Existing
  refusal-eval tests (`tests/evals/test_rag.py` refusal section) still pass;
  update them if the fixture flip changes which questions are in/out of corpus
  and any test asserted on the count.
- Update `backend/evals/baselines/<date>-live.md` after the fix so the
  reference snapshot reflects the corrected refusal row.

# Implementation Notes

- The fixture entry is in `backend/evals/fixtures/golden_qa.json`. The
  related in-corpus story is
  `20260617-superhuman.eml#3` — "Leaked documents show OpenAI lost $38.5B in
  2025" — whose text explicitly says OpenAI "filed confidentially to go
  public just last week." That story *does* establish an IPO filing; it does
  not give a rumored *date*. The honest labeling is probably in-corpus with
  `expected_source_ids=["20260617-superhuman.eml"]`, since a reader of the
  archive would correctly ask this question and correctly be pointed at that
  story — the model did the right thing.
- If you go with labeling in-corpus: also consider whether the
  `answer_faithfulness` eval (T0040's fix aside) would then judge the answer
  fairly. The answer "OpenAI filed confidentially; no rumored date is given"
  is the faithful response and should score well — confirm with a live re-run.
- If you go with keeping the refusal expectation: the 0.35 threshold in
  `app/rag/ask.py` is too coarse to express "retrieval about a *date* should
  clear a higher bar than retrieval about a *topic*." That is a bigger
  mechanism change — flag in findings whether the fix should stay scoped to
  the fixture (one-line change) or escalate. Prefer the one-line fixture fix
  if it's defensible; it is.
- Out of scope: redesigning the guardrail, re-calibrating the 0.35 threshold
  globally, or removing the refusal eval. Just decide this one question's
  label and act on it.