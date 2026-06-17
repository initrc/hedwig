"""Tests for POST /chat (global and topic-scoped).

Every test overrides the RAG dependencies (vector store, embedding function,
and LLM client) so no test touches the real database or the network.  See
``tests/rag/fakes.py`` and ``tests/fakes.py`` for the shared test doubles.
"""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.rag.ask import AugmentedAnswer
from app.rag.store import IndexChunk
from app.routes.chat_routes import (
    get_rag_embed_fn,
    get_rag_llm_client,
    get_rag_vector_store,
)
from tests.fakes import FakeClient, model_reply
from tests.rag.fakes import StubStore, stub_embed

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Two chunks with identical text but different topic labels.  Using the same
# text means both get the same embedding vector from ``stub_embed``, so they
# both match any query with that same text at similarity 1.0.  That lets us
# control which chunks appear via the ``where`` filter rather than via score.
_SHARED_TEXT = (
    "The Federal Reserve decided to hold interest rates steady "
    "at its June 2026 meeting, citing continued inflation progress."
)
[_SHARED_VEC] = stub_embed([_SHARED_TEXT])

_CHUNK_ALPHA = IndexChunk(
    text=_SHARED_TEXT,
    embedding=_SHARED_VEC,
    metadata={
        "digest_date": "2026-06-15",
        "topic_label": "Alpha",
        "source_id": "alpha.eml",
        "source_subject": "Alpha Newsletter",
        "chunk_index": 0,
    },
)

_CHUNK_BETA = IndexChunk(
    text=_SHARED_TEXT,
    embedding=_SHARED_VEC,
    metadata={
        "digest_date": "2026-06-15",
        "topic_label": "Beta",
        "source_id": "beta.eml",
        "source_subject": "Beta Newsletter",
        "chunk_index": 0,
    },
)

# A valid _LLMAnswer JSON that the FakeClient returns.  The LLM is asked to
# cite chunks by digest_date, topic_label, source_subject, and chunk_index,
# so our fake reply cites ALPHA's chunk.
_LLM_JSON = json.dumps({
    "answer": "The Fed held rates steady, citing inflation progress.",
    "sources": [
        {
            "digest_date": "2026-06-15",
            "topic_label": "Alpha",
            "source_subject": "Alpha Newsletter",
            "chunk_index": 0,
        }
    ],
})


def _setup_dependency_overrides(
    *,
    store: StubStore,
    client: FakeClient | None = None,
) -> None:
    """Install test doubles for the three chat dependencies."""
    app.dependency_overrides[get_rag_vector_store] = lambda: store
    app.dependency_overrides[get_rag_embed_fn] = lambda: stub_embed
    app.dependency_overrides[get_rag_llm_client] = (
        lambda: client if client is not None else None
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chat_global_returns_answer_with_sources() -> None:
    """A global query (no topic_id) searches all chunks and returns an answer.

    The store has one chunk; the fake LLM returns a valid answer that cites
    it.  The response should be confident with that answer and source.
    """
    store = StubStore()
    store.insert([_CHUNK_ALPHA])
    client = FakeClient(model_reply(_LLM_JSON))

    _setup_dependency_overrides(store=store, client=client)

    try:
        test_client = TestClient(app)
        response = test_client.post("/chat", json=_SHARED_TEXT)

        assert response.status_code == 200
        body = response.json()
        assert body["confident"] is True
        assert body["answer"] == (
            "The Fed held rates steady, citing inflation progress."
        )
        assert len(body["sources"]) == 1
        source = body["sources"][0]
        assert source["digest_date"] == "2026-06-15"
        assert source["topic_label"] == "Alpha"
        assert source["source_id"] == "alpha.eml"
        assert source["source_subject"] == "Alpha Newsletter"
        assert source["text"] == _SHARED_TEXT

        # Round-trip through the response model.
        AugmentedAnswer.model_validate(body)
    finally:
        app.dependency_overrides.clear()


def test_chat_scoped_to_topic() -> None:
    """A scoped query (with ?topic_id=Alpha) only draws from that topic.

    The store has two chunks with different topics but identical text.  The
    ``where`` filter on the search should exclude the Beta chunk, so the LLM
    only sees (and can cite) the Alpha chunk.
    """
    store = StubStore()
    store.insert([_CHUNK_ALPHA, _CHUNK_BETA])
    client = FakeClient(model_reply(_LLM_JSON))

    _setup_dependency_overrides(store=store, client=client)

    try:
        test_client = TestClient(app)
        response = test_client.post(
            "/chat?topic_id=Alpha", json=_SHARED_TEXT
        )

        assert response.status_code == 200
        body = response.json()
        assert body["confident"] is True
        assert len(body["sources"]) == 1
        # Only Alpha should appear — Beta was filtered out by the where clause.
        assert body["sources"][0]["topic_label"] == "Alpha"
    finally:
        app.dependency_overrides.clear()


def test_chat_no_relevant_content_returns_not_confident() -> None:
    """When the vector store is empty, the guardrail returns confident=False.

    No LLM call is made — the answer is a refusal message.
    """
    store = StubStore()  # empty store
    # No client needed — the guardrail should trip before any LLM call.

    _setup_dependency_overrides(store=store, client=None)

    try:
        test_client = TestClient(app)
        response = test_client.post("/chat", json="some question")

        assert response.status_code == 200
        body = response.json()
        assert body["confident"] is False
        assert len(body["sources"]) == 0
        assert "don't have enough information" in body["answer"]
    finally:
        app.dependency_overrides.clear()


def test_chat_topic_id_not_matched_returns_not_confident() -> None:
    """When topic_id doesn't match any indexed topic, return confident=False.

    This is the same guardrail path as an empty store — the filtered search
    returns no results, so the best score is 0.0, which is below the threshold.
    """
    store = StubStore()
    store.insert([_CHUNK_ALPHA])  # only Alpha exists
    # No client needed — guardrail trips before LLM call.

    _setup_dependency_overrides(store=store, client=None)

    try:
        test_client = TestClient(app)
        response = test_client.post(
            "/chat?topic_id=NonExistentTopic", json=_SHARED_TEXT
        )

        assert response.status_code == 200
        body = response.json()
        assert body["confident"] is False
        assert len(body["sources"]) == 0
    finally:
        app.dependency_overrides.clear()
