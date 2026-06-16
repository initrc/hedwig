---
id: T0014
title: Add embedding and vector store for digest content
status: new
dependencies: []
---

# Scope

- Set up the vector-store and embedding infrastructure so the Day 3 RAG layer has a place to put indexed newsletter text. This task covers the plumbing: pick a vector store, add its dependency, create an embedding client, write a chunker with hand-tuned parameters, and provide a function that indexes every stored digest's source text.

- The deliverable is a callable `build_index(store: DigestStore) -> None` (or similar) that reads all digests from the SQLite store, chunks their `DigestSource.clean_text` fields, embeds each chunk, and upserts them into the vector store keyed by `(digest_date, source_id, chunk_index)`. Nothing is wired to an HTTP endpoint yet — that happens in T0016.

# Acceptance

- A vector-store dependency is added to `pyproject.toml` and the store can be created/queried in-process (no external server needed — Chroma is the recommended default for this).
- An embedding function exists that takes a string (or list of strings) and returns a float vector (or list of vectors). The embedding provider is configurable (at minimum, an environment variable for the API key / base URL).
- A chunker splits long `clean_text` into overlapping chunks. Chunk size and overlap are named constants with a comment explaining **why** those values were chosen (what trade-off they make between retrieval precision and context completeness).
- `build_index()` reads all stored digests via `DigestStore.list_recent()` (or equivalent), chunks every `DigestSource.clean_text`, embeds the chunks, and stores them in the vector store with metadata: `digest_date`, `topic_label`, `source_id`, `source_subject`, and `chunk_index`.
- Re-running `build_index()` replaces the previous index (idempotent — no duplicate chunks).
- Tests use a fake embedding function (returns fixed-dimension vectors) and an in-memory vector store, and verify that chunks are created, embedded, and stored with the expected metadata. No real embedding API calls.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 3 step 1 (lines 146–147): "Embed the parsed items (chunk first — hand-tune chunk size/overlap and be clear on why). Store vectors in a simple store."

- **Vector store choice:** Chroma (`chromadb`) is the first implementation. It runs in-process with a persistent directory on disk (`backend/out/chroma/`), needs no separate server, has a stable Python API, and Claude Code knows its patterns well (the build plan says to delegate vector-store scaffolding to Claude Code). Its dependency footprint is heavier than alternatives, but that does not matter for a local dev tool.

  The design decision is not the store — it is the **interface**. Define a `VectorStore` Protocol with exactly two methods:

  ```python
  class VectorStore(Protocol):
      def search(
          self, query_vector: list[float], *, k: int, filter: dict | None
      ) -> list[ChunkResult]: ...
      def insert(self, chunks: list[IndexChunk]) -> None: ...
  ```

  `ChunkResult` carries the chunk text, metadata dict, and similarity score. `IndexChunk` carries the text, embedding vector, and metadata. T0015's retriever calls only `search` and `insert` — it never imports Chroma directly. This means the store can be swapped later (to LanceDB, pgvector, or a hosted vector DB) by writing a new implementation of those two methods. That pattern is already established in the project: `EmailSource` is a protocol with `LocalEmlSource` and `ImapSource` implementations (`backend/app/ingest/source.py`).

  **Alternatives considered and why they were rejected for now:**
  - `sqlite-vec` (asg017/sqlite-vec) — would reuse the existing `sqlite3` connection and keep everything in one file, but it is pre-v1 with an explicit "expect breaking changes" warning. A scaffolding component should not churn.
  - `sqlite-vector` (sqlite.ai) — unclear Python API story and no visible versioning. Not enough documentation to delegate to Claude Code.
  - LanceDB — works in-process and is lighter than Chroma, but Claude Code has less training data on it, so the scaffolding takes more correction.
  - pgvector — requires a running Postgres server, which this project deliberately avoids ("SQLite is fine"). Revisit when going multi-user.

- **Embedding provider:** Use OpenAI `text-embedding-3-small`. Groq does not offer an embedding endpoint, so this is the project's second API provider. Cost is negligible at demo scale: ~$0.02 per million tokens, which works out to roughly $0.001 to index all 8 sample emails (~40–50K tokens of clean text), and fractions of a cent per chat query (~20 tokens each). The project already has an `.env` pattern for API keys — add `OPENAI_API_KEY` alongside the existing `GROQ_API_KEY`. Wrap the provider behind a thin function `embed(texts: list[str]) -> list[list[float]]` so the rest of the code doesn't care which provider is used.

- **Suggested module layout:**
  - `backend/app/rag/__init__.py` — docstring only (per project convention: thin init, no facade).
  - `backend/app/rag/store.py` — the `VectorStore` Protocol, plus `ChunkResult` and `IndexChunk` types.
  - `backend/app/rag/embed.py` — the `embed()` function and provider setup.
  - `backend/app/rag/chunk.py` — the chunker (`chunk_text(text, size, overlap) -> list[str]`).
  - `backend/app/rag/chroma_store.py` — the Chroma implementation of `VectorStore`.
  - `backend/app/rag/index.py` — `build_index(store: DigestStore, vector_store: VectorStore)` that reads digests, chunks them, and pushes into the vector store via `vector_store.insert()`.

- **Chunking design (hand-tune this):** Start with ~512 tokens of chunk size and ~64 tokens of overlap. The comment should explain: 512 tokens is enough to hold 2–4 paragraphs of newsletter text (enough context for a meaningful answer) while being small enough that retrieval returns the specific passage that answers the query rather than a whole article. The overlap prevents a sentence from being cut exactly at the chunk boundary so the retriever can still find it. Tune these numbers after inspecting real newsletter text lengths — the task file should record the final values and the rationale.

  For the actual splitting, use a simple character-window approach keyed to paragraph boundaries where possible (split on `\n\n` first, then on sentence boundaries within oversized paragraphs). An approximate token count is fine — `len(text) // 4` is a reasonable token estimate for English text.

- **Index metadata:** Each chunk stored in the vector store must carry enough metadata for the T0015 retriever to return citation info:
  ```python
  {
      "digest_date": "2026-06-15",
      "topic_label": "Fed rate decision",
      "source_id": "20250614123456-a1b2c3@newsletter.example.com",
      "source_subject": "Daily Markets Update",
      "chunk_index": 0,
  }
  ```

- **Input data path:** The indexer reads from `DigestStore`. Use `store.list_recent(limit=...)` to get all digests (pass a high limit or add a `list_all` method if needed — check `backend/app/storage/digest_store.py:92`). For each digest, iterate `digest.topics`, then each topic's `sources`, and chunk each source's `clean_text`. The `DigestSource` model is at `backend/app/pipeline/digest.py:24`.

- **Idempotency:** On re-index, clear all existing chunks before inserting new ones, so the caller doesn't accumulate stale chunks across digest re-runs. If the `VectorStore` implementation does not have a `delete_all` method, add one to the Protocol (or pass `clear_before_insert=True` to `build_index` and let the implementation handle it). Chroma supports `collection.delete(where={})`.

- **Test strategy:** Use a fake embedding function that returns a fixed small vector (e.g., `[0.1] * 384` for a 384-dim model) and a fake `VectorStore` that stores chunks in a dict (in-memory) and returns them by brute-force cosine similarity. This keeps the test focused on the indexing logic (chunking, metadata attachment, idempotency) without depending on Chroma or any real embedding API. Create `Digest` fixtures directly (like the T0012 tests do), pass them through a temporary `DigestStore`, and verify `build_index` stores the right number of chunks with the expected metadata.

- **Out of scope:** the retrieval query path (T0015), the chat HTTP endpoints (T0016), and any changes to the `/digest/run` flow (T0016 wires indexing into the endpoint).
