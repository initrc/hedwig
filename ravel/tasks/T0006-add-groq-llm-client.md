---
id: T0006
title: Add Groq LLM client and structured-output helper
status: done
dependencies: []
---

# Scope

- Add the Groq Python SDK (`groq`) as a dependency — this is the LLM SDK that T0001 deliberately deferred to
  Day 2 ("Do not add an LLM SDK yet; that lands in T0005+").
- Create a thin `app.llm` package that every Day 2 pipeline step (T0007–T0010) builds on:
  - A single configured client constructed once (reads `GROQ_API_KEY` from the environment, loaded via
    `load_dotenv()`).
  - A `parse_structured(...)` helper that sends a chat completion and returns a *validated* Pydantic model
    instance, so each pipeline step declares its output schema and gets typed data back instead of
    hand-parsing JSON.
  - A module-level default model constant so the model id lives in one place.
- Document `GROQ_API_KEY` in `.env.example` (placeholder only; the real key lives in `.env`, which is already
  gitignored from T0001).

# Acceptance

- `groq` is declared in `backend/pyproject.toml` and installed via `uv sync`.
- A helper exists (suggested signature) such that a caller can do:
  `parse_structured(messages=[...], schema=SomeModel) -> SomeModel` and receive a validated instance.
- The default model id is `openai/gpt-oss-120b` and is defined in exactly one place.
- `.env.example` lists `GROQ_API_KEY=` with a placeholder value; `.env` is not committed
  (`git check-ignore .env` still passes).
- Unit tests cover the helper's wiring **without hitting the network or spending tokens** — inject a fake/
  stubbed client (e.g. via a constructor argument or monkeypatching) and assert the helper requests the
  schema's JSON shape and returns the parsed model. No test makes a real API call.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 (lines 105–137); the deferral is recorded in
  `T0001` Implementation Notes (line 41).
- **Why Groq + `gpt-oss-120b`:** this pipeline is structured extraction (segment / cluster / summarize /
  select), which does not need a frontier model — a strong open model is plenty, and Groq serves
  `gpt-oss-120b` cheaply and fast. The model id on Groq is `openai/gpt-oss-120b`. Centralizing the id in one
  constant lets a single step swap models later if needed.
- Suggested layout: `backend/app/llm/__init__.py` and `backend/app/llm/client.py`. Keep the package small —
  it is plumbing the learning-core steps depend on, not a step itself.
- **SDK usage:** install with `uv add groq`. Construct with `from groq import Groq; Groq()` — it resolves
  `GROQ_API_KEY` from the environment; do not hardcode the key. (Groq's API is OpenAI-compatible at
  `https://api.groq.com/openai/v1`; the official `groq` SDK is the idiomatic choice over pointing the
  `openai` SDK at that base URL.)
- **Structured output (validate with Pydantic regardless of transport):**
  - Prefer native structured outputs: pass `response_format={"type": "json_schema", "json_schema": {...}}`
    built from the target model's `Model.model_json_schema()`. `gpt-oss-120b` on Groq supports structured
    outputs / tool use.
  - Make the helper **always** validate the returned content with `Model.model_validate_json(...)` and return
    the instance. This keeps the helper correct even if a given model/step has to fall back to JSON-object
    mode (`response_format={"type": "json_object"}`) — validation is the contract, the transport is an
    implementation detail.
  - This mirrors how the codebase already round-trips Pydantic via JSON (`backend/app/ingest/dump.py:25`
    uses `model_dump(mode="json")`).
- **Reasoning effort:** `gpt-oss-120b` is a reasoning model; Groq exposes `reasoning_effort`
  (`low`/`medium`/`high`). Expose it as an optional parameter on the helper (default low/medium) so the
  reasoning-heavier steps (clustering T0008, summarization T0009) can raise it per call. Return only the
  final message content, not the reasoning trace.
- **Default `max_tokens`:** the per-story/cluster payloads here are small; a few thousand tokens is plenty.
  Set a sane default and let callers override.
- **Config loading:** the pipeline steps and their CLIs may run outside the FastAPI app, so don't assume
  `app/main.py:6`'s `load_dotenv()` ran first — call `load_dotenv()` defensively in the `llm` package or
  document that CLI entry points must load it. Construct the client once (behind a small accessor), not per
  call.
- **Testing without spend:** the SDK client is the seam. Make the helper accept an optional `client`
  argument (defaulting to the shared client) so tests pass a fake whose `chat.completions.create` returns a
  stub message with JSON content. mypy is `strict` (see `pyproject.toml`); the `groq` SDK ships type stubs,
  so no `ignore_missing_imports` override should be needed — if mypy complains, prefer typing the seam
  precisely over relaxing strictness.
- Keep `.env.example` edits minimal — append `GROQ_API_KEY=` under the existing IMAP block.
