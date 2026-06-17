---
id: T0017
title: Give embed_fn and LLM client named types for navigable DI
status: new
dependencies: []
---

# Scope

- Give the embedding function a named Protocol (like `EmbedFn`), matching how `VectorStore` and `LLMClient` already work. Replace every `Callable[[list[str]], list[list[float]]]` annotation with the new type.

- Make the LLM client injection explicit at the route level instead of passing `None` and letting `parse_structured` fall through to `get_client()`. The `chat()` and `digest_run()` routes should receive a fully-wired client from their dependency functions, not a `None` that resolves four calls deep.

- After this refactor, every injected RAG dependency (vector store, embedder, LLM client) follows the same pattern: a named Protocol, a DI function that returns the real implementation, and a test stub that implements the same Protocol. A reader can jump from any route parameter to its concrete implementation in two hops: parameter → DI function → real class.

# Acceptance

- A new `EmbedFn` Protocol lives in `app/rag/embed.py`, matching the existing pattern of `VectorStore` in `app/rag/store.py` and `LLMClient` in `app/llm/client.py`.

- Every `Callable[[list[str]], list[list[float]]]` in the codebase (route files, `ask.py`, `index.py`, test fakes, test files) is replaced with `EmbedFn`.

- The `get_rag_llm_client` dependency in `chat_routes.py` returns a `Groq()` client instead of `None`. `get_client()` from `app/llm/client.py` is reused for this purpose — no new factory.

- The `digest_routes.py` file gains a matching LLM client dependency so `/digest/run` can pass it to `run_pipeline` rather than letting it default to `None`. (The current code relies on `run_pipeline`'s internal default, which calls `get_client()` internally.)

- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- **`app/rag/embed.py`** (lines 26–39): Add an `EmbedFn` Protocol above the `embed` function:
  ```python
  class EmbedFn(Protocol):
      def __call__(self, texts: list[str]) -> list[list[float]]: ...
  ```
  The existing `embed` function already satisfies this signature.

- **`app/rag/ask.py`** (line 116): Change `embed_fn` parameter from `Callable[[list[str]], list[list[float]]]` to `EmbedFn`. Update the `_default_embed` import accordingly.

- **`app/rag/index.py`** (lines 35, 107): Change `embed_fn` parameter types in `build_index` and `index_digest` from `Callable[[list[str]], list[list[float]]]` to `EmbedFn`. Remove the `collections.abc.Callable` import if no longer needed.

- **`app/routes/digest_routes.py`** (lines 76, 90): Change `get_embed_fn` return type and `embed_fn` parameter type to `EmbedFn`. Add `get_llm_client` dependency that returns `get_client()` and pass it through to `run_pipeline` and `index_digest`.

- **`app/routes/chat_routes.py`** (lines 47, 58): Change `get_rag_embed_fn` return type and `embed_fn` parameter type to `EmbedFn`. Change `get_rag_llm_client` to return `get_client()` instead of `None`.

- **`tests/rag/fakes.py`** (line 22): Type-annotate `stub_embed` with `EmbedFn` return type.

- **Test files** that use `Callable[[list[str]], list[list[float]]]` in annotations: update to `EmbedFn`.

### Why the LLM client needs fixing too

In `chat_routes.py`, `get_rag_llm_client` returns `None`. `chat()` passes that `None` to `ask()`, which passes it to `_call_llm()`, which passes it to `parse_structured()`, which calls `get_client()` internally (line 132 of `app/llm/client.py`). A reader cannot find the real LLM client from the route — they must trace through four call layers.

After this refactor, `get_rag_llm_client` returns `get_client()` directly. The `client` parameter in `ask()` and `parse_structured()` still accepts `LLMClient | None` so existing callers still work.

### Why the embed function needs fixing

`Callable[[list[str]], list[list[float]]]` is an anonymous type. An IDE cannot resolve it — you must read the dependency function body to find `embed`, then jump to `app/rag/embed.py`. With a named `EmbedFn` Protocol, `Cmd+Click` on the type takes you straight to its definition, and `Cmd+Click` on the DI function takes you to the implementation — the same two-hop navigation that works for `VectorStore` and `LLMClient`.
