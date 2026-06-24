# Eval scorecard baselines

Frozen snapshots of `uv run python evals/run.py` output, kept in the repo so
PRs and follow-up work can point at a concrete "as of date X" number rather
than a result on someone's laptop.

Each file is one run of the runner, named `<date>-live.md` or
`<date>-stubbed.md`:

- `*-stubbed.md` — the CI path: no API calls, no real embeddings, no on-disk
  store. Its numbers prove the harness is wired and every eval returns
  well-formed results; they are **not** measurements of the system. Diff a
  stubbed baseline when you want to detect *harness* changes (new rows,
  renamed aggregates, a broken eval shape).
- `*-live.md` — `--live` runs against the real DeepSeek LLM, real OpenAI
  embeddings, and the on-disk Chroma store. These are the real measurements.
  Diff a live baseline to detect *system* changes (retrieval, faithfulness,
  injection robustness, prompt-version deltas).

A baseline goes stale as code changes — that is the point of dating the
filenames. Do not edit an existing baseline to "update" it; add a new dated
file for the new run. When a follow-up task fixes something a baseline
measured, it should add the post-fix baseline alongside the old one so the
repo keeps the before/after.

## Regenerating

From the `backend/` directory:

```bash
uv run python evals/run.py --out evals/baselines/$(date +%Y-%m-%d)-live.md --live
uv run python evals/run.py --out evals/baselines/$(date +%Y-%m-%d)-stubbed.md
```

## Known issues in the 2026-06-23 live baseline

The 2026-06-23 live baseline is the first one and has known defects captured
as tasks:

- `rag_injection` 0/2 — harness wiring bug in live mode (the runner does not
  seed the injection chunks into the live retrieval store), so the row
  measures nothing. See `ravel/tasks/T0039-fix-live-rag-injection-store-wiring.md`.
- `answer_faithfulness` 0.317 — systematically depressed by an eval-design gap:
  the judge sees less context than the answerer, so faithful restatements of
  chunk-header metadata are scored as hallucinations. See
  `ravel/tasks/T0040-answer-faithfulness-judge-context-gap.md`.
- `retrieval_hit_rate` 0.500 — three real retrieval failure modes (over-merge
  ranking, a topic-label metadata mismatch, date-roving scope). See
  `ravel/tasks/T0041-improve-rag-retrieval-hit-rate.md`.
- `refusal` 0.500 — one golden label is wrong for an archive that contains an
  OpenAI-IPO-adjacent story. See
  `ravel/tasks/T0042-revisit-openai-ipo-refusal-golden-label.md`.

Read those numbers with the above in mind; the headline 0.776 (45/58) is not
a clean measurement of the system until the harness-side issues are fixed.
