"""Answer user questions by retrieving relevant newsletter chunks and asking the
LLM to produce a citation-grounded reply.

The entry point is `ask()`.  Give it a question, a vector store to search, and
optionally a topic to scope to.  It embeds the question, finds the top-*k* most
similar chunks, checks whether the best match is strong enough (the guardrail),
and either returns a polite refusal or formats the chunks into a prompt for the
LLM and returns a sourced answer.

The LLM is told to answer *only* from the provided context and to cite which
source each claim comes from.  The reply is parsed into a structured object so
callers get typed fields, not raw text.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from groq.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.llm.client import LLMClient, parse_structured
from app.rag.embed import EmbedFn
from app.rag.embed import embed as _default_embed
from app.rag.store import ChunkResult, VectorStore

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guardrail threshold
# ---------------------------------------------------------------------------
# When the highest cosine similarity score among the retrieved chunks is below
# this value, the retriever is not confident the chunks are actually about the
# user's question.  Rather than letting the LLM guess (and risk hallucination),
# we return a polite refusal without making an LLM call at all.
#
# Cosine similarity for text embeddings from `text-embedding-3-small`
# typically falls in [0, 1] (normalized vectors).  A score of 0.5 means the
# query and chunk are only loosely related — the chunk may share a word or
# broad topic but is unlikely to contain the specific answer.  Real matches
# for factual questions against newsletter text usually score 0.7 or above.
# We start at 0.5 as a conservative floor; tune this after inspecting real
# query-chunk pairs.
_CONFIDENCE_THRESHOLD: float = 0.5

# How many chunks to retrieve from the vector store per query by default.
_DEFAULT_TOP_K: int = 5


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class _LLMChunk(BaseModel):
    """A chunk label the LLM returns to say "I used this source."

    The model reads these labels from the prompt and echoes back the ones it
    actually drew on.  We match them to the full chunk data we already have.
    """

    digest_date: str
    topic_label: str
    source_subject: str
    chunk_index: int


class _LLMAnswer(BaseModel):
    """The structured answer the LLM returns via `parse_structured`."""

    answer: str
    sources: list[_LLMChunk]


class AugmentedChunk(BaseModel):
    """A source the answer drew on, with everything the UI needs.

    Built by matching the LLM's citation labels against the full chunk data
    from the vector store.
    """

    digest_date: str
    topic_label: str
    source_id: str
    source_subject: str
    text: str
    score: float


class AugmentedAnswer(BaseModel):
    """The result of an `ask()` call.

    When `confident` is `False`, `answer` is a refusal message and
    `sources` is empty — the guardrail tripped and no LLM call was made.
    When `confident` is `True`, `answer` is the LLM's reply and
    `sources` lists the chunks the LLM said it used.
    """

    answer: str
    sources: list[AugmentedChunk]
    confident: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ask(
    query: str,
    *,
    topic_id: str | None = None,
    vector_store: VectorStore,
    k: int = _DEFAULT_TOP_K,
    client: LLMClient | None = None,
    embed_fn: EmbedFn = _default_embed,
) -> AugmentedAnswer:
    """Answer a user question using only their newsletter archive.

    1. Embed the query and retrieve the top-*k* most similar chunks.
    2. If the best similarity score is below the confidence threshold, return a
       refusal (`confident=False`) without calling the LLM.
    3. Otherwise, format the chunks into a prompt, ask the LLM to answer from
       the provided context with inline citations, and return the result.

    When `topic_id` is given, only chunks whose `topic_label` metadata
    matches are searched — the answer is scoped to that topic.

    Pass `embed_fn` and `client` only in tests, to use fakes instead of
    the real embedding API and LLM.
    """
    # 1. Embed the query.
    [query_vector] = embed_fn([query])

    # 2. Search the vector store.
    where: dict[str, str | int] | None
    if topic_id is not None:
        where = {"topic_label": topic_id}
    else:
        where = None
    results = vector_store.search(query_vector, k=k, where=where)

    # 3. Guardrail: is the best match strong enough?
    if not results or results[0].score < _CONFIDENCE_THRESHOLD:
        _logger.info(
            "Query confidence too low (best score=%.3f, threshold=%.3f) — "
            "returning refusal.",
            results[0].score if results else 0.0,
            _CONFIDENCE_THRESHOLD,
        )
        return AugmentedAnswer(
            answer=(
                "I don't have enough information in your newsletters to "
                "answer that question."
            ),
            sources=[],
            confident=False,
        )

    # 4. Build the prompt and ask the LLM.
    messages = _build_messages(query, results)
    llm_answer = _call_llm(messages, client)

    # 5. Match the LLM's citation labels back to full chunk data.
    sources = _resolve_sources(llm_answer.sources, results)

    return AugmentedAnswer(
        answer=llm_answer.answer,
        sources=sources,
        confident=True,
    )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_messages(
    query: str,
    results: list[ChunkResult],
) -> list[ChatCompletionMessageParam]:
    """Build the system and user messages for the LLM call."""
    system: ChatCompletionMessageParam = {
        "role": "system",
        "content": _SYSTEM_PROMPT,
    }

    chunks_text = _format_chunks(results)
    user: ChatCompletionMessageParam = {
        "role": "user",
        "content": (
            f"Below are excerpts from your newsletters, ordered by relevance "
            f"to your question.\n\n"
            f"{chunks_text}\n"
            f"Question: {query}"
        ),
    }

    return [system, user]


_SYSTEM_PROMPT: str = (
    "You are a helpful assistant that answers questions about the user's "
    "newsletter archive.  You must answer **only** from the provided context "
    "chunks.  If the context does not contain enough information to answer "
    "the question, say so honestly rather than guessing or using outside "
    "knowledge.\n\n"
    "In the `sources` list, include every chunk you drew on to produce your "
    "answer.  For each one, copy the `digest_date`, `topic_label`, "
    "`source_subject`, and `chunk_index` exactly as they appear in the chunk "
    "header.  Only list chunks you actually used — do not list every chunk "
    "just because it was provided.\n\n"
    "Write your answer in clear, plain English.  Mention the source "
    "newsletter and date naturally in the answer text when it helps the "
    "reader, for example: \"According to the Daily Markets Update from "
    "June 15, the Fed decided to hold rates steady.\""
)


def _resolve_sources(
    llm_chunks: list[_LLMChunk],
    results: list[ChunkResult],
) -> list[AugmentedChunk]:
    """Match the LLM's citation labels to the full chunk data we already have.

    The LLM returns `_LLMChunk` labels (date, topic, subject).  We look each
    one up in the retrieved `ChunkResult` list and return `AugmentedChunk`
    objects with the full fields the UI needs.
    """
    lookup: dict[tuple[str, str, str, int], ChunkResult] = {}
    for r in results:
        key = (
            str(r.metadata["digest_date"]),
            str(r.metadata["topic_label"]),
            str(r.metadata["source_subject"]),
            int(r.metadata["chunk_index"]),
        )
        if key not in lookup:
            lookup[key] = r

    resolved: list[AugmentedChunk] = []
    for llm_chunk in llm_chunks:
        key = (
            llm_chunk.digest_date,
            llm_chunk.topic_label,
            llm_chunk.source_subject,
            llm_chunk.chunk_index,
        )
        chunk = lookup.get(key)
        if chunk is not None:
            resolved.append(
                AugmentedChunk(
                    digest_date=str(chunk.metadata["digest_date"]),
                    topic_label=str(chunk.metadata["topic_label"]),
                    source_id=str(chunk.metadata["source_id"]),
                    source_subject=str(chunk.metadata["source_subject"]),
                    text=chunk.text,
                    score=chunk.score,
                )
            )
        else:
            _logger.warning(
                "LLM cited a chunk not found in the retrieved results: %s", key
            )

    return resolved


def _format_chunks(results: list[ChunkResult]) -> str:
    """Turn a list of chunk results into a labelled text block for the prompt."""
    parts: list[str] = []
    for i, chunk in enumerate(results):
        meta = chunk.metadata
        header = (
            f"[Chunk {i}]\n"
            f"digest_date: {meta['digest_date']}\n"
            f"topic_label: {meta['topic_label']}\n"
            f"source_subject: {meta['source_subject']}\n"
            f"chunk_index: {meta['chunk_index']}\n"
            f"Text: {chunk.text}"
        )
        parts.append(header)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(
    messages: Iterable[ChatCompletionMessageParam],
    client: LLMClient | None,
) -> _LLMAnswer:
    """Send the prompt to the LLM and return its structured answer."""
    return parse_structured(
        messages=messages,
        schema=_LLMAnswer,
        client=client,
    )
