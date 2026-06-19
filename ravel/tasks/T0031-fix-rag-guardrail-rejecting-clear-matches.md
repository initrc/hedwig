---
id: T0031
title: Fix RAG guardrail rejecting clear matches
status: done
dependencies: []
---

# Scope

- Stop the RAG chat from returning "I don't have enough information in your
  newsletters to answer that question" for questions whose answers are clearly
  stated in a topic's source text.
- Shrink newsletter chunks so each one stays on a single passage instead of
  spanning several unrelated stories, and re-calibrate the confidence guardrail
  to the similarity range `text-embedding-3-small` actually produces on this
  archive.

# Acceptance

- A specific factual question whose answer is in an indexed chunk (for example,
  "What is the context window size of GLM-5.2?") returns `confident: true` with
  a sourced answer, not a refusal.
- Clearly off-topic questions (weather, recipes, car prices) are still rejected
  with `confident: false` and no LLM call.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.
- The on-disk Chroma store is re-indexed so the fix takes effect without a
  manual clear.

# Implementation Notes

- The refusal comes from the guardrail in `backend/app/rag/ask.py:145`:
  `if not results or results[0].score < _CONFIDENCE_THRESHOLD`. Reproduced
  against the live store — clear factual questions scored 0.29-0.42, below the
  old 0.5 threshold, so the guardrail tripped on every specific question.

- Root cause is chunk size, not the threshold alone. The sample newsletters
  (AlphaSignal, Superhuman) arrive as one dense block with no blank-line
  paragraph breaks, so the paragraph splitter in `chunk.py` rarely fires and
  chunks fill to `CHUNK_SIZE` off sentence boundaries. At 2048 chars a single
  chunk mixed the Cursor Origin story, the GLM-5.2 spec, and a Retool ad — a
  focused question only weakly matches that blend. A focused ~300-char passage
  scored 0.53 against the same question; the 2048-char chunk scored 0.38.

- `backend/app/rag/chunk.py`: lower `CHUNK_SIZE` 2048 -> 512 and `CHUNK_OVERLAP`
  256 -> 128. The new header comment explains *why* in terms of the dense
  single-paragraph samples, not just abstract token math. `text-embedding-3-small`
  embeddings are unaffected (the model embeds any length); only chunk granularity
  changes.

- `backend/app/rag/ask.py`: lower `_CONFIDENCE_THRESHOLD` 0.5 -> 0.35. The new
  comment records the empirical calibration: focused chunks with the answer
  score 0.45-0.60, unrelated questions score at most ~0.24, so 0.35 sits in the
  gap with margin on both sides. The original 0.5 assumed "real matches score
  0.7+", which never occurs for these embeddings on this corpus.

- `backend/tests/rag/test_chunk.py`: the overlap test hardcoded `"A" * 2040`,
  which now exceeds the new `CHUNK_SIZE` and would merge into a single chunk.
  Switched to `"A" * (CHUNK_SIZE - 8)` so it stays relative to the constant.
  The stale "below the 0.5 threshold" comment in `tests/rag/test_ask.py` is
  updated to "well below the confidence threshold".

- Re-indexed the local Chroma store with `build_index`; chunk count went 86 ->
  400. On a fresh checkout the startup runner re-indexes automatically, but an
  existing SQLite db with sources already recorded in `ingested_sources` will
  skip the run (the `should_run_digest` guard in `runner.py`), and even if that
  guard were bypassed the runner would re-run the full LLM pipeline — not what
  a re-chunk needs. `build_index` is the correct lever: it reads the digests
  already persisted in SQLite and only re-chunks + re-embeds them (OpenAI
  embeddings only, no DeepSeek), and `delete_all()` inside it clears Chroma so
  no stale large chunks remain. Note `build_index` has no production caller —
  only `index_digest` is wired in (`runner.py:94`) — so it must be invoked
  directly for now:
  ```bash
  cd backend && uv run python -c "
  from dotenv import load_dotenv; load_dotenv()
  from app.rag.chroma_store import ChromaStore
  from app.rag.embed import embed
  from app.rag.index import build_index
  from app.storage.digest_store import DigestStore, DEFAULT_DB_PATH
  n = build_index(digest_store=DigestStore(db_path=DEFAULT_DB_PATH), vector_store=ChromaStore(), embed_fn=embed)
  print('indexed', n, 'chunks')
  "
  ```
  No need to remove the SQLite db or the Chroma directory; `build_index`
  rebuilds the vector store in place.

- Verified end-to-end: `ask("What is the context window size of GLM-5.2?",
  topic_label="Z.ai GLM-5.2 model", ...)` returns `confident: true`, answer
  "The context window size of GLM-5.2 is 1 million tokens." with a source.
  Full suite: 172 tests pass, ruff and mypy clean.

- The chunking constants were introduced in T0014 and the guardrail in T0015;
  neither was changed since, so the mismatch was latent and only surfaced once
  the dense AlphaSignal/Superhuman samples became the indexed content.
