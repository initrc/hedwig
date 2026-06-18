---
id: T0025
title: Disable DeepSeek thinking for simple pipeline stages
status: done
dependencies:
  - T0024
---

# Scope

- Add a `thinking: bool = True` parameter to `parse_structured` that toggles
  DeepSeek's chain-of-thought mode via `extra_body={"thinking": {"type":
  "enabled"/"disabled"}}`.
- Disable thinking on the two simplest pipeline stages — segmentation
  (`segment.py`) and image selection (`image.py`) — where the model extracts
  or picks rather than reasons.
- Add per-call timing and token-usage logging to `parse_structured` so a real
  run shows which stages cost the most wall-clock time.

# Acceptance

- `parse_structured` accepts a `thinking` parameter and passes the toggle
  through to DeepSeek via `extra_body`.
- Segmentation and image selection call `parse_structured` with
  `thinking=False`; cluster, summarize, and ask keep the default (`True`).
- Each `parse_structured` call logs its schema name, thinking state, elapsed
  seconds, and token usage at INFO level.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- The `extra_body` parameter is an OpenAI SDK pass-through: the SDK sends it
  as extra JSON fields in the request body, which DeepSeek reads as its
  thinking toggle. Documented at
  https://api-docs.deepseek.com/guides/thinking_mode.
- The `_Completions` Protocol in `client.py` and the fake completions in
  `tests/fakes.py` must accept `extra_body` so the fakes still satisfy the
  Protocol and record the toggle for test assertions.

# Measured findings (8-email `POST /digest/run`)

Baseline (T0024, thinking on everywhere): **450 s (7.5 min)**, 26 topics.

With thinking off for segment + image: **225 s (3.75 min)**, 19 topics.

Per-stage breakdown (thinking off for segment + image):

| Stage        | Calls | Thinking | Total   | Avg/call |
|--------------|-------|----------|---------|----------|
| Segmentation | 8     | off      | 67.3 s  | 8.4 s    |
| Clustering   | 1     | on       | 44.2 s  | 44.2 s   |
| DraftSummary | 19    | on       | 68.7 s  | 3.6 s    |
| ImageChoice  | 19    | off      | 25.0 s  | 1.3 s    |
| **Total**    | 47    |          | 205 s   |          |

Observations:
- **50% wall-clock reduction** from disabling thinking on just two of four
  stages.
- **Image selection quality improved**: with thinking off, more cards got
  images. The thinking mode appears to make the model over-deliberate on a
  simple index pick and return null instead of committing — hurting both
  speed and quality. This suggests thinking is not useful for DeepSeek-v4-flash
  on simple structured tasks.
- **Clustering is the single slowest call** (44 s with thinking on, one call
  that reasons over every story pair). This is the next candidate for a
  thinking-off experiment.
- DeepSeek's `usage.completion_tokens` was not populated in json_object mode
  responses, so the token column is unreliable; timing is the trustworthy
  signal.
