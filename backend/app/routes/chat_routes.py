"""POST /chat — answer user questions by searching the indexed newsletter archive.

Two flavours:
- ``POST /chat`` — searches across all indexed digests.
- ``POST /chat?topic_label=...`` — scopes the search to chunks from a single
  digest topic, for the detail-panel chat in the frontend.

The RAG pipeline (embed, retrieve, generate) is injected via FastAPI
dependencies so tests can override it with fakes — no network calls
needed in the test suite.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.llm.client import LLMClient, get_client
from app.rag.ask import AugmentedAnswer, ask
from app.rag.chroma_store import ChromaStore
from app.rag.embed import EmbedFn, embed
from app.rag.store import VectorStore

chat_router = APIRouter()


@lru_cache(maxsize=1)
def get_rag_vector_store() -> VectorStore:
    """Build the ChromaStore once and reuse it across requests.

    Override this dependency in tests to use an in-memory stub with
    pre-loaded chunks.
    """
    return ChromaStore()


def get_rag_embed_fn() -> EmbedFn:
    """Return the real embedding function.

    Override this dependency in tests to use a deterministic stub.
    """
    return embed


def get_rag_llm_client() -> LLMClient:
    """Return the LLM client for answer generation.

    Returns the shared Groq client so a reader can trace from the route
    parameter straight to the real implementation in one hop.  Override
    this dependency in tests with a ``FakeClient`` to keep tests off the
    network.
    """
    return get_client()


@chat_router.post("/chat")
def chat(
    query: Annotated[str, Body()],
    vector_store: Annotated[VectorStore, Depends(get_rag_vector_store)],
    embed_fn: Annotated[EmbedFn, Depends(get_rag_embed_fn)],
    client: Annotated[LLMClient, Depends(get_rag_llm_client)],
    topic_label: Annotated[str | None, Query()] = None,
) -> AugmentedAnswer:
    """Answer a question using the indexed newsletter archive.

    When ``topic_label`` is given, only chunks from that topic are searched —
    the answer is scoped to one card's sources.  When omitted, the search
    covers every indexed digest.
    """
    return ask(
        query,
        topic_label=topic_label,
        vector_store=vector_store,
        embed_fn=embed_fn,
        client=client,
    )
