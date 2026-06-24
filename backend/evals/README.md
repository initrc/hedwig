# Eval suite

Run the evals from the `backend/` directory.

## Quick start

Run from the `backend/` directory, through `uv` (the project's venv doesn't
show up on your bare `python` PATH):

```bash
uv run python evals/run.py          # stubbed (no API calls, CI-safe)
uv run python evals/run.py --live   # score against the real models
```

The stubbed run prints a scorecard that proves the harness is wired end to end.
Its numbers are **not** real measurements — use `--live` for that.

## Writing the scorecard to a file

```bash
uv run python evals/run.py --out evals/scorecard.md
```

## Live mode

Live mode uses the real DeepSeek LLM, OpenAI embeddings, and the on-disk Chroma
store. It needs API keys and costs money, so it's opt-in. Enable it with `--live`
or by setting the environment variable:

```bash
HEDWIG_EVAL_LIVE=1 uv run python evals/run.py
```

The output header marks a run as `LIVE` or `STUBBED` so a stubbed scorecard is
never mistaken for real numbers.