"""RAG evals: retrieval hit rate, answer faithfulness, and low-confidence refusal.

Each function scores one slice of the retrieve-then-generate path used by
`app.rag.ask.ask()` — the same entry point the `/chat` endpoints call — against
the golden Q&A fixture from `evals.dataset`. They inject `vector_store`,
`embed_fn`, and `client` exactly as the chat tests do (`backend/tests/rag/`), so
the evals measure the real retrieval + generation path without touching the
network. The same dependency-injection seams that make the RAG layer testable
make it evaluable.

Three slices:

* `eval_retrieval_hit_rate` — the retrieval half only (embed + search), no LLM.
  For each in-corpus question, does any of its `expected_source_ids` come back
  in the top-*k* chunks? Scoring retrieval without the LLM call keeps this eval
  cheap and isolates retrieval quality (chunking, embedding, the confidence
  threshold) from generation quality.
* `eval_answer_faithfulness` — the full `ask()` path, then the summary-quality
  LLM-as-judge from `evals.summarize` reused **as-is** on the answer with the
  retrieved chunks as the "source text." Prior to the judge, a cheap
  deterministic citation-coverage pre-check fails the question outright when
  `ask()` refused or cited no chunks. The aggregate score is the mean of the
  judge's *faithfulness* dimension across the questions that reach the judge;
  the pre-check failures count as 0.0 toward it.
* `eval_refusal` — runs `ask()` on the out-of-corpus questions and asserts the
  guardrail fired: `confident=False` **and** no LLM call was made. The "no LLM
  call" half is verified by handing `ask()` a counting client inside this
  function and reading its `call_count`; it must stay at zero. When a question
  is not refused (the threshold let a chunk through, or the golden label is
  wrong), the eval records a failure rather than crashing the suite.
"""

from __future__ import annotations

from app.llm.fake_client import FakeClient, model_reply
from app.llm.protocol import LLMClient
from app.pipeline.digest import DigestSource, DigestTopic
from app.rag.ask import AugmentedAnswer, ask
from app.rag.embed import EmbedFn
from app.rag.store import VectorStore
from evals.dataset import GoldenQA
from evals.summarize import judge_topic
from evals.types import EvalResult

# ---------------------------------------------------------------------------
# Refusal-path counting client
# ---------------------------------------------------------------------------
# `eval_refusal` needs to prove the guardrail short-circuited before the LLM
# call. We pass `ask()` a `FakeClient` that records every `ask()` and returns a
# benign valid reply; the eval then reads `call_count`. The guardrail refusing
# means the counter stays at zero — that is the assertion.


# A minimal valid `_LLMAnswer` reply (see `app.rag.ask`): enough for `ask()` to
# validate against the schema and build a confident answer. The refusal eval
# never inspects this text — only `confident` and `call_count`.
_NON_REFUSAL_REPLY = '{"answer": "stub", "sources": []}'


# ---------------------------------------------------------------------------
# Retrieval hit rate
# ---------------------------------------------------------------------------


def eval_retrieval_hit_rate(
    questions: list[GoldenQA],
    *,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
    k: int = 5,
) -> list[EvalResult]:
    """Score retrieval (embed + search) against each in-corpus golden question.

    For each question with `expect_refusal=False`, embeds the query and searches
    the store for the top-*k* chunks (scoped by `topic_label` when the question
    sets one), then scores a hit when any retrieved chunk's `source_id` is in
    the question's `expected_source_ids`. No LLM call is made — this measures
    retrieval only.

    Returns one `EvalResult` per in-corpus question (named
    `retrieval_hit_rate/{i}`) plus an aggregate `retrieval_hit_rate` whose
    `score` is the hit rate over those questions.
    """
    in_corpus = [q for q in questions if not q.expect_refusal]

    results: list[EvalResult] = []
    hits = 0

    for i, q in enumerate(in_corpus):
        [query_vector] = embed_fn([q.question])
        where: dict[str, str | int] | None
        if q.topic_label:
            where = {"topic_label": q.topic_label}
        else:
            where = None
        retrieved = vector_store.search(query_vector, k=k, where=where)

        retrieved_ids = {str(r.metadata.get("source_id")) for r in retrieved}
        expected = set(q.expected_source_ids)
        hit = not retrieved_ids.isdisjoint(expected)
        if hit:
            hits += 1

        scope_note = f" scoped to topic={q.topic_label}" if q.topic_label else ""
        results.append(
            EvalResult(
                name=f"retrieval_hit_rate/{i}",
                passed=hit,
                score=1.0 if hit else 0.0,
                detail=(
                    f'question="{q.question}" '
                    f"expected={sorted(expected)} "
                    f"retrieved={sorted(retrieved_ids)} "
                    f"{'HIT' if hit else 'MISS'}"
                    f"{scope_note}"
                ),
            )
        )

    if not in_corpus:
        results.append(
            EvalResult(
                name="retrieval_hit_rate",
                passed=True,
                score=1.0,
                detail="No in-corpus questions to evaluate.",
            )
        )
        return results

    hit_rate = hits / len(in_corpus)
    results.append(
        EvalResult(
            name="retrieval_hit_rate",
            passed=hit_rate >= 0.5,
            score=hit_rate,
            detail=f"Aggregate hit rate: {hit_rate:.3f} over {len(in_corpus)} in-corpus questions.",
        )
    )
    return results


# ---------------------------------------------------------------------------
# Answer faithfulness
# ---------------------------------------------------------------------------


def _answer_to_topic(i: int, answer: AugmentedAnswer) -> DigestTopic:
    """Build a `DigestTopic` so the summary-quality judge can read the RAG answer.

    The judge prompt (in `evals.summarize`) compares a summary
    against its `sources`' `subject` and `clean_text`. We map the retrieved
    chunks `ask()` returned onto exactly that shape: each cited `AugmentedChunk`
    becomes a `DigestSource` with its `source_subject` as the subject and its
    chunk `text` as the body, and the answer becomes the topic's `summary`.
    Reusing the existing judge core keeps one rubric for the whole suite.
    """
    sources = [
        DigestSource(
            id=chunk.source_id,
            source=chunk.source_id,
            subject=chunk.source_subject,
            original_url=None,
            clean_text=chunk.text,
        )
        for chunk in answer.sources
    ]
    return DigestTopic(label=f"rag_answer/{i}", summary=answer.answer, sources=sources)


def eval_answer_faithfulness(
    questions: list[GoldenQA],
    *,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
    client: LLMClient,
    judge_client: LLMClient,
) -> list[EvalResult]:
    """Score the full `ask()` answer's faithfulness to its retrieved sources.

    For each in-corpus question, runs `ask()` and applies the summary-quality
    LLM-as-judge from `evals.summarize` (the same `RubricScore` rubric) to the
    answer with the retrieved chunks as the source text. The per-question
    `score` is the judge's `faithfulness` dimension — the dimension an invented
    fact would tank — and the aggregate score is the mean of the per-question
    scores (questions that fail the pre-check count as 0.0).

    A cheap deterministic **citation-coverage pre-check** fails the question
    outright when `ask()` refused (`confident=False`) or returned no cited
    chunks: an answer that refused or cited nothing has nothing for the judge to
    verify against, and the refusal itself is a faithfulness failure for an
    in-corpus question the archive should answer. Only questions that pass the
    pre-check reach the LLM judge; the aggregate still averages them all in.
    """
    in_corpus = [q for q in questions if not q.expect_refusal]

    results: list[EvalResult] = []
    scores: list[float] = []

    for i, q in enumerate(in_corpus):
        answer = ask(
            q.question,
            topic_label=q.topic_label,
            vector_store=vector_store,
            embed_fn=embed_fn,
            client=client,
        )

        if not answer.confident or not answer.sources:
            scores.append(0.0)
            results.append(
                EvalResult(
                    name=f"answer_faithfulness/{i}",
                    passed=False,
                    score=0.0,
                    detail=(
                        f'question="{q.question}" '
                        f"citation-coverage pre-check failed: "
                        f"confident={answer.confident} "
                        f"cited_sources={len(answer.sources)} "
                        f"(refusal or no citations for an in-corpus question)."
                    ),
                )
            )
            continue

        rubric = judge_topic(
            _answer_to_topic(i, answer), judge_client=judge_client
        )
        scores.append(rubric.faithfulness)
        results.append(
            EvalResult(
                name=f"answer_faithfulness/{i}",
                passed=rubric.faithfulness >= 0.5,
                score=rubric.faithfulness,
                detail=(
                    f'question="{q.question}" '
                    f"faithfulness={rubric.faithfulness:.2f} "
                    f"conciseness={rubric.conciseness:.2f} "
                    f"coherence={rubric.coherence:.2f} "
                    f"cited_sources={len(answer.sources)}. "
                    f"Rationale: {rubric.rationale}"
                ),
            )
        )

    if not in_corpus:
        results.append(
            EvalResult(
                name="answer_faithfulness",
                passed=True,
                score=1.0,
                detail="No in-corpus questions to evaluate.",
            )
        )
        return results

    avg = sum(scores) / len(scores)
    results.append(
        EvalResult(
            name="answer_faithfulness",
            passed=avg >= 0.5,
            score=avg,
            detail=(
                f"Aggregate mean faithfulness: {avg:.3f} over {len(in_corpus)} "
                f"in-corpus questions (pre-check failures scored 0.0)."
            ),
        )
    )
    return results


# ---------------------------------------------------------------------------
# Low-confidence refusal
# ---------------------------------------------------------------------------


def eval_refusal(
    questions: list[GoldenQA],
    *,
    vector_store: VectorStore,
    embed_fn: EmbedFn,
) -> list[EvalResult]:
    """Assert the guardrail refuses out-of-corpus questions with no LLM call.

    For each out-of-corpus question (`expect_refusal=True`), runs `ask()` with a
    counting client and asserts both halves of the refusal contract:

    * `AugmentedAnswer.confident` is `False` (the refusal path ran), and
    * the client's `call_count` stayed at zero (the LLM was never called).

    When `ask()` does not refuse an out-of-corpus-marked question — meaning the
    threshold let a matching chunk through, or the golden label is wrong — the
    eval records a failure (with `confident` and `llm_calls` in the detail)
    rather than crashing. Returns one `EvalResult` per out-of-corpus question
    (named `refusal/{i}`) plus an aggregate `refusal` whose `score` is the
    fraction of questions that refused cleanly.
    """
    out_of_corpus = [q for q in questions if q.expect_refusal]

    results: list[EvalResult] = []
    clean_refusals = 0

    for i, q in enumerate(out_of_corpus):
        client = FakeClient(model_reply(_NON_REFUSAL_REPLY))
        answer = ask(
            q.question,
            topic_label=q.topic_label,
            vector_store=vector_store,
            embed_fn=embed_fn,
            client=client,
        )

        refused = answer.confident is False and client.call_count == 0
        if refused:
            clean_refusals += 1

        results.append(
            EvalResult(
                name=f"refusal/{i}",
                passed=refused,
                score=1.0 if refused else 0.0,
                detail=(
                    f'question="{q.question}" '
                    f"confident={answer.confident} "
                    f"llm_calls={client.call_count} "
                    f"{'REFUSED' if refused else 'NOT REFUSED'}"
                ),
            )
        )

    if not out_of_corpus:
        results.append(
            EvalResult(
                name="refusal",
                passed=True,
                score=1.0,
                detail="No out-of-corpus questions to evaluate.",
            )
        )
        return results

    rate = clean_refusals / len(out_of_corpus)
    results.append(
        EvalResult(
            name="refusal",
            passed=rate == 1.0,
            score=rate,
            detail=(
                f"Aggregate refusal rate: {rate:.3f} over "
                f"{len(out_of_corpus)} out-of-corpus questions."
            ),
        )
    )
    return results


__all__ = [
    "eval_answer_faithfulness",
    "eval_refusal",
    "eval_retrieval_hit_rate",
]
