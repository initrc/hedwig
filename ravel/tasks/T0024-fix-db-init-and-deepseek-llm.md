---
id: T0024
title: Fix db initialization and switch LLM to DeepSeek
status: done
dependencies: []
---

# Scope

- Fix `DigestStore` so it creates its parent directory before opening the
  SQLite database, eliminating the `unable to open database file` error on a
  fresh checkout.
- Rename the runtime artifact directory from `out/` to `db/` across the three
  modules that write there (digest store, item dump, Chroma index), and update
  `.gitignore` and the backend README to match.
- Replace the Groq LLM client with a DeepSeek client (`deepseek-v4-flash`) via
  its OpenAI-compatible endpoint, and adapt `parse_structured` to DeepSeek's
  `json_object` response format.
- Update the env example, dependencies, and tests.

# Acceptance

- `GET /digests` returns 200 with `[]` on a fresh checkout where `db/` does
  not exist (the directory is auto-created).
- `POST /digest/run` completes end-to-end against DeepSeek without rate-limit
  errors.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass; `pnpm run
  lint` and `pnpm run build` pass.
- `.env.example` documents `DEEPSEEK_API_KEY` and keeps `OPENAI_API_KEY` for
  embeddings.

# Implementation Notes

- DigestStore: `backend/app/storage/digest_store.py:42` — add
  `db_path.parent.mkdir(parents=True, exist_ok=True)` before
  `sqlite3.connect`, mirroring `dump.py:26`. `sqlite3.connect` does not create
  parent dirs, so a missing `db/` is what produced the 500.
- Rename `out/` -> `db/`: `DEFAULT_DB_PATH` at `digest_store.py:20`,
  `DEFAULT_OUTPUT` at `dump.py:19`, `DEFAULT_CHROMA_DIR` at
  `chroma_store.py:24`; update the docstrings, `.gitignore` (`out/` -> `db/`),
  and `backend/README.md`.
- LLM client: `backend/app/llm/client.py` — replace the `groq` SDK with the
  `openai` SDK pointed at `https://api.deepseek.com`. `get_client()` returns
  an `OpenAI` client configured with `DEEPSEEK_API_KEY`. Default model
  `deepseek-v4-flash`.
- Response format: DeepSeek supports `response_format={'type':
  'json_object'}` only, not `json_schema` (verified at
  https://api-docs.deepseek.com/guides/json_mode). `parse_structured` must
  inject the Pydantic schema (as JSON Schema text) into the prompt and still
  validate the reply with `schema.model_validate_json`. Keep the
  `reasoning_effort` parameter — DeepSeek supports it through the OpenAI SDK
  (verified at https://api-docs.deepseek.com/guides/thinking_mode). Update the
  `ReasoningEffort` type to `Literal["low", "medium", "high", "xhigh"]`
  (DeepSeek maps low/medium→high and xhigh→max). Keep the default at `"high"`
  (DeepSeek's regular-request default for structured calls); `"xhigh"`/`"max"`
  is intended for agentic contexts and produces chain-of-thought long enough to
  truncate a single JSON reply, so no caller overrides the default for now.
- Truncation handling: `parse_structured` checks `finish_reason == "length"`
  and raises a clear `ValueError` (citing `max_tokens`) instead of letting
  pydantic emit a confusing "EOF while parsing". `DEFAULT_MAX_TOKENS` raised
  from 4096 to 16384 to give any single pipeline stage's JSON reply headroom.
- Call sites of `parse_structured`: `segment.py:88`, `cluster.py:122`,
  `summarize.py:120`, `image.py:147`, `rag/ask.py:298`. The `LLMClient`
  Protocol shape (`.chat.completions.create`) is identical between the Groq
  and OpenAI SDKs, so the test fakes in `tests/fakes.py` largely survive —
  verify and adjust.
- DeepSeek `json_object` mode requires the word "json" in the prompt and may
  occasionally return empty content (per the docs). Handle the empty-content
  case with a clear error or a retry.
- Deps: `pyproject.toml` already has `openai>=2.0.0` (used by `rag/embed.py`);
  drop `groq>=1.4.0`.
- Env: `.env.example` — replace `GROQ_API_KEY` with `DEEPSEEK_API_KEY`.
- The db-directory rename and `mkdir` fix are already present in the working
  tree from the T0019 review; they become part of this task's single commit.
  The `out/` convention originated in T0004; the Groq client was added in
  T0006.
