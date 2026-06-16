---
id: T0016
title: Expose POST /chat and POST /chat with topic scope
status: new
dependencies: []
---

# Scope

- Wire the RAG retrieval + generation from T0015 into FastAPI HTTP endpoints so Day 4's frontend can call them. Expose two routes: `POST /chat` for global search across all indexed newsletters, and `POST /chat?topic_id=...` for scoped chat pinned to one digest topic's sources (the detail-panel chat from the build plan).

- Also hook indexing into the existing `POST /digest/run` flow so every newly generated digest is immediately searchable — the chat endpoints return up-to-date results with no separate indexing step.

# Acceptance

- `POST /chat` accepts a JSON body `{"query": "what did the finance newsletter say about rate cuts?"}` and returns a JSON response matching the `RagAnswer` schema from T0015 (`{answer, sources[], confident}`).
- `POST /chat?topic_id=...` accepts the same body but scopes retrieval to chunks belonging to that topic. When `topic_id` does not match any indexed topic, the endpoint returns `confident=False` with an appropriate message (not a 404).
- Indexing is wired into `POST /digest/run`: after persisting the new digest, the endpoint also indexes its source texts into the vector store. Existing digests are not re-indexed (only the new one). The `/digest/run` response is unchanged — indexing is a side effect.
- The existing `GET /health` and `POST /digest/run` endpoints still work without regression.
- Tests use FastAPI's `TestClient` with dependency overrides (fake embedding, fake LLM, in-memory vector store and SQLite store) and verify: a global query returns an answer with sources; a scoped query only draws from the matching topic; a query with no relevant content returns `confident=False`; indexing happens automatically after `/digest/run`. No real API calls.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 3 step 4 (lines 152–153): "Expose `POST /chat` (global) and `POST /chat?topic_id=...` (scoped to one card's sources, for Day 4's detail panel)."

- **Suggested module:** `backend/app/routes/chat_routes.py`, following the pattern established by `backend/app/routes/digest_routes.py`. Register the router in `backend/app/main.py` alongside the existing `digest_router`.

- **Route design (mirror digest_routes.py):**

  ```python
  chat_router = APIRouter()

  class ChatRequest(BaseModel):
      query: str

  @chat_router.post("/chat")
  def chat(
      body: ChatRequest,
      topic_id: str | None = None,  # query parameter
      rag: Annotated[..., Depends(get_rag)] = ...,
  ) -> RagAnswer:
      return rag.ask(body.query, topic_id=topic_id)
  ```

  The `topic_id` is a query parameter (`/chat?topic_id=...`), not a path segment, because it's optional — matching the build plan's notation.

- **Dependency injection for testability:** Use FastAPI's `Depends()` to inject the RAG function (or a wrapper object), the digest store, and the LLM client — exactly as `digest_routes.py` does. This lets tests override them via `app.dependency_overrides` with fakes. The existing fake patterns are in `backend/tests/fakes.py`.

  Provide a `get_rag()` dependency that builds the RAG components (embedding function, vector store, LLM client) wired to the real implementations. Tests override this to return a stub `ask()` that returns a fixed `RagAnswer`.

- **Wire indexing into /digest/run:** In `backend/app/routes/digest_routes.py`, after `store.save(digest)`, call the index function from T0014 to index the new digest's source texts. The indexer needs access to the vector store and embedding function — inject these as additional dependencies on the `/digest/run` endpoint, or create an `index_digest(digest, vector_store, embed_fn)` helper that the route calls.

  Design note: indexing a single new digest is incremental — it adds chunks to the existing collection rather than rebuilding the whole index. This means T0014's `build_index()` should have a companion `index_digest(digest)` for incremental additions. If that wasn't scoped in T0014, add a minimal version here (same chunk → embed → upsert logic, scoped to one digest).

- **Error handling:** If the vector store is empty (no digests have been indexed yet), `POST /chat` should return `confident=False` with a message like "No newsletters have been indexed yet. Generate a digest first." — not a 500. The guardrail threshold from T0015 handles this naturally if the empty-store query returns a very low score, but also add an explicit check for zero results before calling the LLM.

- **No streaming:** Both endpoints return the complete `RagAnswer` synchronously (not streamed). The digest generation endpoint (`/digest/run`) is already synchronous and may take several seconds; the chat endpoint should be faster because it's one embedding call + one LLM call. If chat latency becomes a concern, streaming can be added later — it's not in this scope.

- **Register the router in main.py:**

  ```python
  from app.routes.chat_routes import chat_router
  app.include_router(chat_router)
  ```

  Match the existing pattern at `backend/app/main.py:12`.

- **Out of scope:** the Day 4 frontend (card list, detail sheet, scoped chat UI), the Day 5 eval harness, and any authentication/multi-user concerns (the endpoints are open for local use).
