"""Tests for `app.rag.ask` — the retrieve-then-generate flow.

Every test uses `StubStore` for the vector store, a fixed embedding function,
and `FakeClient` for the LLM.  No real API calls are made.
"""

from __future__ import annotations

import json
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from app.llm.fake_client import FakeClient, model_reply
from app.rag.ask import AugmentedAnswer, ask
from app.rag.embed import EmbedFn
from app.rag.store import IndexChunk
from tests.rag.fakes import StubStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_message(messages: list[ChatCompletionMessageParam]) -> str:
    """Return the content of the single user turn in the recorded messages.

    `parse_structured` prepends a schema-instruction system message, so the
    caller's user turn is no longer at a fixed index — select it by role.
    """
    users = [
        m for m in cast(list[dict[str, object]], messages) if m.get("role") == "user"
    ]
    assert len(users) == 1
    return str(users[0]["content"])


def _task_system_message(messages: list[ChatCompletionMessageParam]) -> str:
    """Return the caller's system prompt, not the schema instruction.

    `parse_structured` prepends a schema-instruction system message; the caller's
    own system prompt is the other system turn. We pick it by its content.
    """
    systems = [
        str(m["content"])
        for m in cast(list[dict[str, object]], messages)
        if m.get("role") == "system"
    ]
    task = [s for s in systems if "newsletter archive" in s.lower()]
    assert len(task) == 1
    return task[0]


def _json_reply(obj: object) -> FakeClient:
    """Build a `FakeClient` that returns *obj* as a JSON string.

    `parse_structured` calls `schema.model_validate_json(content)`, so
    the fake client's content must be valid JSON matching the schema
    that `ask()` passes to `parse_structured`.
    """
    return FakeClient(model_reply(json.dumps(obj)))


def _fixed_embed(*, value: list[float]) -> EmbedFn:
    """Return an embed function that always returns *value* for every text."""

    def fn(texts: list[str]) -> list[list[float]]:
        return [value for _ in texts]

    return fn


# ---------------------------------------------------------------------------
# ask() tests
# ---------------------------------------------------------------------------


def test_ask_returns_confident_answer_with_sources_for_strong_match() -> None:
    """When the top chunk has a high similarity score, the LLM is called and
    its answer is returned with the chunks it cited as sources."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="The Fed cut interest rates by 25 basis points on June 15.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Rate Cuts",
                "source_id": "finance.eml",
                "chunk_index": 0,
            },
        )
    ])

    fake_client = _json_reply({
        "answer": (
            "According to the Daily Finance Brief from June 15, the Fed cut "
            "interest rates by 25 basis points."
        ),
        "sources": [
            {
                "digest_date": "2026-06-15",
                "topic_label": "Rate Cuts",
                "source_id": "finance.eml",
                "chunk_index": 0,
            }
        ],
    })

    # The query vector exactly matches the stored chunk vector, so cosine
    # similarity is 1.0 — well above the threshold.
    result = ask(
        "Did the Fed cut rates?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    assert isinstance(result, AugmentedAnswer)
    assert result.confident is True
    assert "cut" in result.answer.lower()
    assert len(result.sources) == 1
    assert result.sources[0].digest_date == "2026-06-15"
    assert result.sources[0].topic_label == "Rate Cuts"
    assert result.sources[0].source_id == "finance.eml"
    assert result.sources[0].text == (
        "The Fed cut interest rates by 25 basis points on June 15."
    )
    assert result.sources[0].score == 1.0


def test_ask_returns_not_confident_when_best_score_below_threshold() -> None:
    """When no chunk is similar enough to the query, the guardrail returns
    `confident=False` and no LLM call is made."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="The Fed cut interest rates by 25 basis points.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Rate Cuts",
                "source_id": "finance.eml",
                "chunk_index": 0,
            },
        )
    ])

    # Never called — we assert that below.
    fake_client = _json_reply({"answer": "should not be used", "sources": []})

    # The query embedding is orthogonal to the stored chunk (cosine sim = 0.0),
    # which is well below the confidence threshold.
    result = ask(
        "What is the weather on Mars?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[0.0, 0.0, 1.0]),
        client=fake_client,
    )

    assert result.confident is False
    assert "don't have enough information" in result.answer.lower()
    assert result.sources == []

    # The LLM must not have been called.
    assert fake_client.call_count == 0


def test_ask_scoped_to_topic_only_returns_matching_chunks() -> None:
    """When `topic_label` is passed, only chunks with that `topic_label` are
    searched, so the sources and prompt only include that topic."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="Apple announced a new iPhone.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Tech",
                "source_id": "tech.eml",
                "chunk_index": 0,
            },
        ),
        IndexChunk(
            text="The Fed held rates steady.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Finance",
                "source_id": "finance.eml",
                "chunk_index": 0,
            },
        ),
    ])

    fake_client = _json_reply({
        "answer": "The Fed held rates steady.",
        "sources": [
            {
                "digest_date": "2026-06-15",
                "topic_label": "Finance",
                "source_id": "finance.eml",
                "chunk_index": 0,
            }
        ],
    })

    result = ask(
        "Any finance news?",
        topic_label="Finance",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    assert result.confident is True
    assert len(result.sources) == 1
    assert result.sources[0].topic_label == "Finance"
    assert result.sources[0].source_id == "finance.eml"

    # Also verify the prompt only includes the Finance chunk, not the Tech one.
    user_content = _user_message(fake_client.messages)
    assert "Fed held rates steady" in user_content
    assert "Apple announced" not in user_content


def test_ask_prompt_includes_chunk_metadata_for_citations() -> None:
    """The LLM prompt must include each chunk's newsletter name, date, and
    topic so the model can produce citations like "according to the Daily
    Markets Update from June 15..."."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="Oil prices rose 3% on supply concerns.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-14",
                "topic_label": "Commodities",
                "source_id": "markets.eml",
                "chunk_index": 0,
            },
        )
    ])

    fake_client = _json_reply({
        "answer": "Oil prices rose.",
        "sources": [
            {
                "digest_date": "2026-06-14",
                "topic_label": "Commodities",
                "source_id": "markets.eml",
                "chunk_index": 0,
            }
        ],
    })

    ask(
        "What happened with oil prices?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    # Inspect the prompt that was sent to the LLM.
    messages = fake_client.messages
    system_msg = _task_system_message(messages)
    user_msg = _user_message(messages)

    # System prompt tells the model its role and citation rules.
    assert "newsletter archive" in system_msg.lower()
    assert "only" in system_msg.lower()

    # User prompt includes chunk metadata.
    assert "2026-06-14" in user_msg
    assert "Commodities" in user_msg
    assert "Oil prices rose 3%" in user_msg


def test_ask_returns_not_confident_when_store_is_empty() -> None:
    """An empty vector store produces no results, which trips the guardrail."""
    store = StubStore()
    fake_client = _json_reply({"answer": "unused", "sources": []})

    result = ask(
        "Any news?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    assert result.confident is False
    assert result.sources == []
    assert fake_client.call_count == 0


def test_ask_drops_llm_sources_not_found_in_retrieved_chunks() -> None:
    """If the LLM invents a source label that doesn't match any retrieved
    chunk, it is silently dropped rather than returned to the caller."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="The Fed cut rates.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Rate Cuts",
                "source_id": "finance.eml",
                "chunk_index": 0,
            },
        )
    ])

    fake_client = _json_reply({
        "answer": "Rates were cut.",
        "sources": [
            {
                "digest_date": "2026-06-15",
                "topic_label": "Rate Cuts",
                "source_id": "finance.eml",
                "chunk_index": 0,
            },
            {
                "digest_date": "2099-01-01",
                "topic_label": "Future News",
                "source_id": "future.eml",
                "chunk_index": 0,
            },
        ],
    })

    result = ask(
        "Did the Fed cut rates?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    assert result.confident is True
    # Only the real source is kept; the invented one is dropped.
    assert len(result.sources) == 1
    assert result.sources[0].source_id == "finance.eml"


def test_ask_returns_empty_sources_when_llm_cites_none() -> None:
    """The LLM may return an empty sources list.  The answer is still returned."""
    store = StubStore()
    store.insert([
        IndexChunk(
            text="Markets were mixed on Tuesday.",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "digest_date": "2026-06-15",
                "topic_label": "Markets",
                "source_id": "markets.eml",
                "chunk_index": 0,
            },
        )
    ])

    fake_client = _json_reply({
        "answer": "Markets were mixed on Tuesday according to the newsletter.",
        "sources": [],
    })

    result = ask(
        "How were markets?",
        vector_store=store,
        embed_fn=_fixed_embed(value=[1.0, 0.0, 0.0]),
        client=fake_client,
    )

    assert result.confident is True
    assert "mixed" in result.answer
    assert result.sources == []
