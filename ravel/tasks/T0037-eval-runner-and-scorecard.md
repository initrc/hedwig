---
id: T0037
title: Eval runner and scorecard
status: done
dependencies:
  - T0033
  - T0034
  - T0035
  - T0036
---

# Scope

- Build the `evals/run.py` entry point (build-plan Day 5 step 6 and the end-of-day deliverable) that
  runs the whole suite — categorization/summarization (T0033), RAG (T0034), safety (T0035), and
  prompt-version comparison (T0036) — and prints a markdown scorecard with the numbers.
- Gate the evals that need real LLM/embedding calls behind a `--live` flag (or env var) so the
  harness runs in CI with stubs by default and produces real numbers only when explicitly asked.
- This is the build-plan's "point to numbers, not vibes" moment: `python evals/run.py` prints a
  scorecard; `python evals/run.py --live` prints one scored against the real models.

# Acceptance

- `backend/evals/run.py` runs every eval from T0033–T0036, collects their `list[EvalResult]` into a
  `Scorecard` (defined in T0032), and prints a markdown table to stdout. The table shows, per eval:
  name, pass rate (or mean score), and the `detail` note (e.g. "3/5 golden sources retrieved",
  "judge drift +0.1 vs human", "v2 −0.03 conciseness vs v1"). A summary line gives overall pass rate.
- `python evals/run.py` (no flags) runs **without real API calls** — it uses stubbed LLM/embedding
  fakes and exercises the wiring end to end. This is the CI path; it validates that every eval
  function is callable and returns well-formed `EvalResult`s, and that the scorecard renders.
- `python evals/run.py --live` (or `HEDWIG_EVAL_LIVE=1`) uses the real LLM and embedding clients and
  the real vector store, producing the actual scorecard against the labeled set. A clear header in
  the output marks a live run so a stubbed scorecard is never mistaken for real numbers.
- Optionally writes the scorecard to a file (e.g. `backend/evals/scorecard.md`) when `--out` is
  passed; the build-plan's "a tab in the dashboard" option is noted as a future extension and is not
  required for this task.
- Tests for the runner live in `backend/tests/evals/` and run **without real API calls**: feed fake
  `EvalResult`s (or fake eval functions) and assert the markdown table has the expected rows,
  columns, and summary line. Assert that without `--live` the runner never constructs a real client.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 6 (line 213): "Output a simple results
  table (markdown or a tab in the dashboard)." And the end-of-day bar (line 215): "python evals/run.py
  prints a scorecard; you can point to numbers, not vibes."
- **Run from `backend/`.** The project's cwd convention is the backend directory
  (`DEFAULT_DB_PATH = Path("db/hedwig.db")` is relative to cwd, `backend/app/storage/digest_store.py:28`,
  and tests run from `backend/`). So `evals/run.py` lives at `backend/evals/run.py` and is invoked as
  `python evals/run.py` (or `uv run python evals/run.py`) from `backend/`, matching the build-plan
  wording exactly. Import `app.*` modules the same way the tests do.
- **Aggregation:** each eval function (T0033–T0036) returns `list[EvalResult]`; the runner collects
  them all into one `Scorecard` (T0032) and renders. Keep the rendering dumb — a fixed table over
  `EvalResult.{name, passed, score, detail}` — so adding an eval later means only adding a call in
  `run.py`, not touching the renderer. This is the same "thin composition" pattern T0011 used to
  assemble the pipeline stages.
- **Live vs stubbed is the key design decision.** Real evals need real LLM calls (the judge, the
  summarization, the RAG answer) and real embeddings (retrieval hit rate). Default to stubbed so the
  harness runs in CI without API keys and so a `--live` run is a deliberate, billable act. The
  stubbed run still has value: it proves every eval function is wired and returns the right shape,
  and it's the path the runner's own tests assert. Document the split at the top of `run.py` so no
  one reads a stubbed scorecard as "the system works."
- **What "live" swaps in:** when live, construct the real `LLMClient` (T0006), the real `embed`
  (T0014, `backend/app/rag/embed.py`), and the real `ChromaStore` (T0014,
  `backend/app/rag/chroma_store.py`) pointed at the on-disk index. The RAG evals (T0034) then score
  the same `ask()` path the chat endpoints serve. When stubbed, use the `FakeClient`
  (`backend/tests/fakes.py`) and `StubStore` (`backend/tests/rag/fakes.py`) the eval tests already
  use, so the runner and the unit tests share fakes.
- **Scorecard output format:** a markdown table is the build-plan default ("markdown or a tab in the
  dashboard"). Keep it plain so it pastes cleanly into a PR comment or a file. Reserve the dashboard
  tab (a Next.js route reading the scorecard) as a noted future extension — do not build it here;
  Day 5 time is for the numbers, not a new frontend surface.
- **Failure isolation:** one eval raising should not kill the run. Catch per-eval exceptions, emit an
  `EvalResult` with `passed=False` and the error in `detail`, and continue, so the scorecard always
  shows a full picture even if one probe blows up. A masked failure is still visible (it's a row in
  the table), which is better than a half-printed scorecard that hides the rest.
- **Out of scope:** the per-eval scoring logic (T0033–T0036), the labeled fixtures and shared schema
  (T0032), and a dashboard scorecard tab (future). This task is the orchestrator + renderer + the
  live/stubbed switch.
