"""Tests for `evals.rag` — retrieval hit rate, answer faithfulness, refusal.

No real API calls: `StubStore` and `stub_embed`/fixed-embed back the retrieval,
and `FakeClient` supplies both the `ask()` answer and the LLM-as-judge reply.
"""

from __future__ import annotations

import json
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from app.llm.fake_client import FakeClient, model_reply
from app.rag.embed import EmbedFn
from app.rag.store import IndexChunk
from evals.dataset import GoldenQA
from evals.rag import (
    eval_answer_faithfulness,
    eval_refusal,
    eval_retrieval_hit_rate,
)
from evals.summarize import RubricScore
from tests.rag.fakes import StubStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixed_embed(value: list[float]) -> EmbedFn:
    """An embed function that returns *value* for every input text."""

    def fn(texts: list[str]) -> list[list[float]]:
        return [list(value) for _ in texts]

    return fn


def _chunk(
    *,
    text: str,
    source_id: str,
    embedding: list[float],
    topic_label: str = "Any",
    source_subject: str = "Daily Brief",
    digest_date: str = "2026-06-15",
    chunk_index: int = 0,
) -> IndexChunk:
    return IndexChunk(
        text=text,
        embedding=embedding,
        metadata={
            "digest_date": digest_date,
            "topic_label": topic_label,
            "source_id": source_id,
            "source_subject": source_subject,
            "chunk_index": chunk_index,
        },
    )


def _ask_reply(*, answer: str, source_id: str, subject: str = "Daily Brief") -> FakeClient:
    """A fake `ask()` LLM that answers and cites the given source chunk."""
    return FakeClient(
        model_reply(
            json.dumps(
                {
                    "answer": answer,
                    "sources": [
                        {
                            "digest_date": "2026-06-15",
                            "topic_label": "Any",
                            "source_subject": subject,
                            "chunk_index": 0,
                        }
                    ],
                }
            )
        )
    )


def _judge_client(
    *,
    faithfulness: float = 0.9,
    conciseness: float = 0.8,
    coherence: float = 0.85,
) -> FakeClient:
    """A fake judge that returns the given rubric scores for `ask()` answers."""
    score = RubricScore(
        faithfulness=faithfulness,
        conciseness=conciseness,
        coherence=coherence,
        rationale="Cited chunk backs the answer.",
    )
    return FakeClient(model_reply(score.model_dump_json()))


def _user_message(messages: list[ChatCompletionMessageParam]) -> str:
    users = [
        m for m in cast("list[dict[str, object]]", messages) if m.get("role") == "user"
    ]
    assert len(users) == 1
    return str(users[0]["content"])


# ---------------------------------------------------------------------------
# Retrieval hit rate
# ---------------------------------------------------------------------------


def test_hit_rate_scores_a_hit_when_golden_source_is_in_the_store() -> None:
    """A question whose `expected_source_ids` are retrieved scores a hit."""
    store = StubStore()
    store.insert([
        _chunk(
            text="Several new open-source LLMs shipped this week.",
            source_id="alpha-signal.eml",
            embedding=[1.0, 0.0, 0.0],
        )
    ])

    questions = [
        GoldenQA(
            question="Which new open-source LLMs were released?",
            expected_source_ids=["alpha-signal.eml"],
        )
    ]
    results = eval_retrieval_hit_rate(
        questions,
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
    )

    # 1 per-question result + 1 aggregate.
    assert len(results) == 2
    assert results[0].name == "retrieval_hit_rate/0"
    assert results[0].passed is True
    assert results[0].score == 1.0
    assert results[1].name == "retrieval_hit_rate"
    assert results[1].score == 1.0
    assert results[1].passed is True


def test_hit_rate_scores_a_miss_when_no_matching_chunk_is_retrieved() -> None:
    """When the store only holds an unrelated source, the question misses."""
    store = StubStore()
    store.insert([
        _chunk(
            text="An unrelated newsletter about sports.",
            source_id="sports.eml",
            embedding=[1.0, 0.0, 0.0],
        )
    ])

    questions = [
        GoldenQA(
            question="Which new open-source LLMs were released?",
            expected_source_ids=["alpha-signal.eml"],
        )
    ]
    results = eval_retrieval_hit_rate(
        questions,
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
    )

    assert results[0].passed is False
    assert results[0].score == 0.0
    assert "MISS" in results[0].detail
    # Aggregate over one question: 0/1 hit rate.
    assert results[1].score == 0.0
    assert results[1].passed is False


def test_hit_rate_aggregates_across_hit_and_miss() -> None:
    """Mixed hit + miss produces an aggregate hit rate of 0.5."""
    store = StubStore()
    store.insert([
        _chunk(text="Match source.", source_id="match.eml", embedding=[1.0, 0.0, 0.0]),
        _chunk(text="Other source.", source_id="other.eml", embedding=[0.0, 1.0, 0.0]),
    ])

    questions = [
        GoldenQA(question="q-hit", expected_source_ids=["match.eml"]),
        GoldenQA(question="q-miss", expected_source_ids=["alpha-signal.eml"]),
    ]
    results = eval_retrieval_hit_rate(
        questions,
        vector_store=store,
        # Query vector matches the first chunk only.
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
    )

    # 2 per-question + 1 aggregate.
    assert len(results) == 3
    assert results[0].passed is True
    assert results[1].passed is False
    assert results[2].score == 0.5


def test_hit_rate_skips_refusal_questions() -> None:
    """Refusal-marked questions are not scored by retrieval hit rate."""
    store = StubStore()
    questions = [
        GoldenQA(question="In-corpus q", expected_source_ids=["ok.eml"]),
        GoldenQA(question="Out-of-corpus q", expect_refusal=True),
    ]
    results = eval_retrieval_hit_rate(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )

    # Only the in-corpus question was scored.
    assert len(results) == 2
    assert results[0].name == "retrieval_hit_rate/0"
    assert results[1].name == "retrieval_hit_rate"


def test_hit_rate_scopes_by_topic_label_when_set() -> None:
    """A question with `topic_label` searches only that topic's chunks."""
    store = StubStore()
    store.insert([
        _chunk(
            text="Midjourney body scanner details.",
            source_id="alpha-signal.eml",
            embedding=[1.0, 0.0, 0.0],
            topic_label="Midjourney body scanner",
        ),
        _chunk(
            text="Unrelated finance topic.",
            source_id="other.eml",
            embedding=[1.0, 0.0, 0.0],
            topic_label="Finance",
        ),
    ])

    questions = [
        GoldenQA(
            question="Where can I access Midjourney's body scanner?",
            expected_source_ids=["alpha-signal.eml"],
            topic_label="Midjourney body scanner",
        )
    ]
    results = eval_retrieval_hit_rate(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )

    assert results[0].passed is True
    assert "scoped to topic=Midjourney body scanner" in results[0].detail


# ---------------------------------------------------------------------------
# Answer faithfulness
# ---------------------------------------------------------------------------


def test_faithfulness_passes_when_judge_scores_high() -> None:
    """An answer that cites a retrieved chunk and scores high on faithfulness passes."""
    store = StubStore()
    store.insert([
        _chunk(
            text="Several new open-source LLMs shipped this week.",
            source_id="alpha-signal.eml",
            embedding=[1.0, 0.0, 0.0],
        )
    ])

    questions = [
        GoldenQA(
            question="Which new open-source LLMs were released?",
            expected_source_ids=["alpha-signal.eml"],
        )
    ]
    results = eval_answer_faithfulness(
        questions,
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
        client=_ask_reply(
            answer="According to the Daily Brief, several new open-source LLMs shipped this week.",
            source_id="alpha-signal.eml",
        ),
        judge_client=_judge_client(faithfulness=0.9),
    )

    assert len(results) == 2
    assert results[0].name == "answer_faithfulness/0"
    assert results[0].passed is True
    assert results[0].score == 0.9
    assert "faithfulness=0.90" in results[0].detail
    assert results[1].score == 0.9


def test_faithfulness_fails_pre_check_when_ask_refuses() -> None:
    """When `ask()` refuses on an in-corpus question, faithfulness fails without
    calling the judge."""
    store = StubStore()
    store.insert([
        # Orthogonal embedding → cosine sim 0.0, below the guardrail threshold.
        _chunk(
            text="Irrelevant text.",
            source_id="alpha-signal.eml",
            embedding=[0.0, 1.0, 0.0],
        )
    ])

    questions = [
        GoldenQA(
            question="Which new open-source LLMs were released?",
            expected_source_ids=["alpha-signal.eml"],
        )
    ]
    # The judge must never be reached; a real-judge marker would be unused.
    judge = FakeClient(model_reply("should not be used"))
    results = eval_answer_faithfulness(
        questions,
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
        client=FakeClient(model_reply("unused — guardrail trips first")),
        judge_client=judge,
    )

    assert results[0].passed is False
    assert results[0].score == 0.0
    assert "pre-check failed" in results[0].detail
    # The judge was never called.
    assert judge.call_count == 0


def test_faithfulness_judge_prompt_includes_retrieved_chunk_text() -> None:
    """The judge prompt must carry the retrieved chunk text so it can verify the answer."""
    store = StubStore()
    store.insert([
        _chunk(
            text="A new open-source model called Lite-7 was released.",
            source_id="alpha-signal.eml",
            embedding=[1.0, 0.0, 0.0],
            source_subject="Alpha Signal",
        )
    ])

    judge = _judge_client(faithfulness=0.9)
    eval_answer_faithfulness(
        [
            GoldenQA(
                question="Which new open-source LLMs were released?",
                expected_source_ids=["alpha-signal.eml"],
            )
        ],
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
        client=_ask_reply(
            answer="Lite-7 was released.",
            source_id="alpha-signal.eml",
            subject="Alpha Signal",
        ),
        judge_client=judge,
    )

    user_content = _user_message(judge.messages)
    assert "A new open-source model called Lite-7 was released." in user_content
    assert "Alpha Signal" in user_content


def test_faithfulness_empty_questions_returns_single_result() -> None:
    """No in-corpus questions → one aggregate result with score 1.0."""
    store = StubStore()
    results = eval_answer_faithfulness(
        [GoldenQA(question="x", expect_refusal=True)],
        vector_store=store,
        embed_fn=_fixed_embed([1.0, 0.0, 0.0]),
        client=FakeClient(model_reply("{}")),
        judge_client=FakeClient(model_reply("{}")),
    )
    assert len(results) == 1
    assert results[0].name == "answer_faithfulness"
    assert results[0].score == 1.0


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


def test_refusal_returns_clean_refusal_when_score_below_threshold() -> None:
    """An out-of-corpus question whose only chunk scores below the threshold
    is refused with no LLM call."""
    store = StubStore()
    store.insert([
        # Orthogonal vector → cosine similarity 0.0, below the 0.35 threshold.
        _chunk(
            text="Newsletter about something else entirely.",
            source_id="finance.eml",
            embedding=[0.0, 1.0, 0.0],
        )
    ])

    questions = [GoldenQA(question="What's the weather forecast for Tokyo?", expect_refusal=True)]
    results = eval_refusal(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )

    assert len(results) == 2
    assert results[0].name == "refusal/0"
    assert results[0].passed is True
    assert results[0].score == 1.0
    assert "confident=False" in results[0].detail
    assert "llm_calls=0" in results[0].detail
    assert results[1].name == "refusal"
    assert results[1].score == 1.0


def test_refusal_clean_when_store_empty() -> None:
    """An empty store returns no chunks → guardrail refuses, no LLM call."""
    store = StubStore()
    questions = [GoldenQA(question="Out of corpus?", expect_refusal=True)]
    results = eval_refusal(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )
    assert results[0].passed is True
    assert results[1].score == 1.0


def test_refusal_flags_failure_when_ask_does_not_refuse() -> None:
    """When `ask()` does not refuse an out-of-corpus-marked question, the eval
    records a failure (the threshold let a chunk through, or the golden label
    is wrong) without crashing.

    The setup is deliberately artificial: a chunk whose embedding matches the
    query so retrieval scores 1.0 and clears the threshold, but the question is
    marked `expect_refusal=True`. That setup inverts what the guardrail should
    see in real data — a genuinely matching chunk means the question is in
    corpus — so the eval's job is to surface the contradiction as a finding, not
    to assert the guardrail "leaked." The counting client just counts; it does
    not raise.
    """
    store = StubStore()
    store.insert([
        _chunk(
            text="A chunk whose embedding matches the query.",
            source_id="finance.eml",
            embedding=[1.0, 0.0, 0.0],
        )
    ])

    questions = [GoldenQA(question="Out of corpus?", expect_refusal=True)]
    results = eval_refusal(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )

    assert results[0].passed is False
    assert results[0].score == 0.0
    assert "NOT REFUSED" in results[0].detail
    assert results[1].passed is False
    assert results[1].score == 0.0


def test_refusal_skips_in_corpus_questions() -> None:
    """In-corpus questions are not scored by the refusal eval."""
    store = StubStore()
    questions = [
        GoldenQA(question="In-corpus q", expected_source_ids=["ok.eml"]),
        GoldenQA(question="Out-of-corpus q", expect_refusal=True),
    ]
    results = eval_refusal(
        questions, vector_store=store, embed_fn=_fixed_embed([1.0, 0.0, 0.0])
    )
    # Only the out-of-corpus question was scored (1 per-question + 1 aggregate).
    assert len(results) == 2
    assert results[0].name == "refusal/0"
    assert results[1].name == "refusal"