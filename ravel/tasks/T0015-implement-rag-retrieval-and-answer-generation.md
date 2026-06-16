---
id: T0015
title: Implement RAG retrieval and answer generation with guardrail
status: new
dependencies: []
---

# Scope

- Build the retrieval + generation half of the RAG layer: given a user question, embed it, retrieve the top-k most relevant chunks from the vector store, format them into a prompt for the LLM, and return a citation-grounded answer. Add a low-confidence guardrail that refuses to answer when the retrieved chunks are too weak, rather than letting the model hallucinate.

- The deliverable is a callable `ask(query: str, *, topic_id: str | None = None) -> RagAnswer` that runs the full retrieve-then-generate flow and returns a typed result with the answer text, the sources it drew from, and a confidence signal.

# Acceptance

- A `RagAnswer` Pydantic model exists with fields: `answer: str`, `sources: list[ChunkRef]` (the chunks the answer cited or drew from), and `confident: bool` (whether the retriever found strong-enough matches).
- `ask(query, ...)` embeds the query, retrieves the top-k chunks (default k=5), formats them into an LLM prompt that instructs the model to answer only from the provided context and cite which source each claim comes from, parses the LLM reply into a `RagAnswer`, and returns it.
- The prompt to the LLM includes the chunk text and its source metadata (newsletter name, date, topic) so the model can produce citations like "according to the Daily Markets Update from June 15…".
- **Guardrail:** when the highest retrieval similarity score is below a threshold, `ask()` returns immediately with `confident=False` and `answer="I don't have enough information in your newsletters to answer that question."` (or similar) — no LLM call is made. The threshold is a named constant with a comment explaining how it was chosen.
- **Scoped retrieval:** when `topic_id` is passed, the retriever filters chunks to only those belonging to that topic (using the `topic_label` metadata stored in T0014). When `topic_id` is `None`, retrieval searches across all indexed digests.
- Tests stub the embedding function and the LLM call (fake vectors, fake completion) and verify: a query with strong matches returns a `confident=True` answer with sources; a query with weak matches returns `confident=False` and no LLM call was made; the scoped filter only returns chunks from the right topic. No real API calls.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 3 steps 2–3 (lines 148–153): "Retrieve + generate. On a query, retrieve top-k chunks, pass to the LLM with a citation-grounded answer prompt. Guardrail: if retrieval confidence is low, the agent says 'I don't have that in your newsletters' rather than hallucinating."

- **Suggested module:** `backend/app/rag/retrieve.py` for the retrieval logic (query embedding → `vector_store.search()` → top-k chunks with scores), and `backend/app/rag/generate.py` for the LLM answer-generation prompt and parsing. Alternatively, keep it in one `backend/app/rag/ask.py` file if the two phases are tightly coupled. The retriever calls only the `VectorStore` Protocol from T0014 — it never imports Chroma directly.

- **Retrieval flow:**
  1. Embed the query string with the same embedding function from T0014 (`backend/app/rag/embed.py`).
  2. Call `vector_store.search(query_vector, k=5, filter=...)` — this calls through the `VectorStore` Protocol from T0014, so the retriever is not coupled to Chroma. The result is a list of `ChunkResult` objects each carrying `text`, `metadata`, and `score`.
  3. Check the top score. If it is below the confidence threshold, short-circuit: return `confident=False` with a polite refusal message and empty sources. **Hand-tune this threshold** — start at 0.5 (for cosine similarity) and adjust after inspecting real query-chunk pairs. Document the final value and how it was calibrated.
  4. If scores are strong enough, format the chunks into an LLM prompt.

- **LLM prompt design (hand-tune this — it's the core prompt-engineering surface for Day 3):** The prompt should include:
  - A system message that tells the model it is answering questions about the user's newsletter archive. It must **only** answer from the provided context chunks. If the context doesn't contain the answer, it should say so rather than guessing. It should cite sources inline (e.g., "[Source: Daily Markets Update, June 15]").
  - A user message that presents the retrieved chunks (each labeled with its source metadata — newsletter name, date, topic) followed by the user's question.
  
  Use `parse_structured()` from T0006 (`backend/app/llm/client.py:111`) with a Pydantic schema for the answer so the model's reply is machine-readable. The schema should include the answer text and a list of source references (matching chunk metadata fields). Avoid inventing source details — the LLM should reference sources by the labels provided in the prompt.

- **Similarity/distance convention:** The `VectorStore.search()` method returns a similarity score in each `ChunkResult`. The score direction is defined by the Protocol: higher = more similar (cosine similarity, range roughly 0 to 1 for normalized embeddings). The guardrail threshold compares against this score — a threshold of ~0.5 is a reasonable starting point. If the Chroma implementation returns cosine distance (lower = more similar), convert it inside the implementation so callers only see the "higher is better" convention.

- **Scoped retrieval:** When `topic_id` is provided, pass it as the filter to `vector_store.search(query_vector, k=5, filter={"topic_label": topic_id})`. This relies on the metadata stored by T0014's `build_index()`. The `topic_id` in this context is the topic's `label` string (e.g., "Fed rate decision"), which matches `DigestTopic.label` from `backend/app/pipeline/digest.py:39`.

- **Types to define:**
  ```python
  class ChunkRef(BaseModel):
      digest_date: str
      topic_label: str
      source_id: str
      source_subject: str
      chunk_index: int
      text: str
      score: float  # similarity score from the vector store

  class RagAnswer(BaseModel):
      answer: str
      sources: list[ChunkRef]
      confident: bool
  ```

- **Test strategy:**
  - Build a small fake vector store with a handful of pre-computed chunks and known fake embedding vectors.
  - Stub the LLM call via the `client` parameter of `parse_structured()` (the fake client pattern from `backend/tests/fakes.py`).
  - Test cases: (a) query matches a chunk → gets answer with source; (b) query matches nothing (low similarity) → `confident=False`, no LLM call; (c) topic-scoped query only returns chunks with matching `topic_label`.
  - Verify that the LLM prompt includes the chunk text and metadata, so the model has the context it needs to cite sources.

- **Out of scope:** the HTTP endpoints (T0016), any changes to the indexing flow (T0014), and streaming/chunked responses (return the full answer synchronously).
