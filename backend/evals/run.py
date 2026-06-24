"""Eval suite runner — run every eval, collect a Scorecard, print a markdown table.

Two modes
---------

**Stubbed (default).** ``python evals/run.py`` wires fake LLM/embedding/store
doubles through every eval function and prints a scorecard. The
numbers a stubbed run produces are **not real measurements** — they only prove
the harness is wired end to end and every eval function returns well-formed
``EvalResult`` objects. A stubbed scorecard is never a signal that the system works; a
clear header in the output marks it as stubbed so it is never mistaken for real
numbers. This is the CI path: it runs without API keys and without the on-disk
vector index.

**Live.** ``python evals/run.py --live`` (or ``HEDWIG_EVAL_LIVE=1``) swaps in the
real DeepSeek LLM, the real OpenAI embedding function, and the on-disk Chroma
store, producing the actual scorecard against the labeled set. A live run is a
deliberate, billable act — that is why it is opt-in.

Both modes share one renderer and one ``Scorecard``, so the only
difference is which clients the eval functions receive. Run from ``backend/``
(the project's cwd convention): ``python evals/run.py``.

Failure isolation
-----------------

One eval raising must not kill the run. Each eval call is wrapped so an exception
becomes a failing ``EvalResult`` (the error in its ``detail``) and the next eval
still runs, so the scorecard always shows the full picture rather than a
half-printed table that hides the rest.
"""

from __future__ import annotations

# ruff: noqa: E402 -- the sys.path shim below must run before the imports it fixes.
# --- sys.path shim -----------------------------------------------------------
# When run as `python evals/run.py`, Python puts this script's directory
# (`backend/evals/`) at the front of sys.path. That directory holds our own
# `types.py`, which then shadows the standard library `types` module and breaks
# `import argparse` (argparse -> re -> enum -> types). Repoint sys.path at the
# backend directory instead, so stdlib imports resolve normally and `evals.*`
# imports as a package -- the same layout pytest uses with `pythonpath = ["."]`.
# This runs before any import that transitively reaches `types`.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _HERE in sys.path:
    sys.path.remove(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
# ---------------------------------------------------------------------------

import argparse
import json
from collections.abc import Callable
from typing import Any

from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from pydantic import BaseModel

from app.llm.client import OpenAIClient
from app.llm.protocol import LLMClient, _ClientBase
from app.pipeline.cluster import _SYSTEM_PROMPT as _CLUSTER_PROMPT
from app.pipeline.digest import Digest
from app.pipeline.prompts import DEFAULT_PROMPT_VERSION, SUMMARIZE_PROMPTS
from app.pipeline.segment import _SYSTEM_PROMPT as _SEGMENT_PROMPT
from app.pipeline.segment import Story
from app.rag.ask import _SYSTEM_PROMPT as _RAG_PROMPT
from app.rag.embed import EmbedFn
from app.rag.store import IndexChunk, VectorStore
from evals.categorize import eval_topic_assignment
from evals.dataset import load_golden_qa, load_topic_labels
from evals.injection import (
    eval_pipeline_injection,
    eval_rag_injection,
    load_injection_items,
    load_injection_questions,
)
from evals.prompt_comparison import _build_digest, _group_stories_by_label, eval_prompt_comparison
from evals.rag import (
    eval_answer_faithfulness,
    eval_refusal,
    eval_retrieval_hit_rate,
)
from evals.summarize import _JUDGE_SYSTEM_PROMPT as _JUDGE_PROMPT
from evals.summarize import RubricScore, eval_judge_calibration, eval_summary_quality
from evals.types import EvalResult, Scorecard

# The env var that flips the runner into live mode, matching `--live`.
_LIVE_ENV = "HEDWIG_EVAL_LIVE"


# ---------------------------------------------------------------------------
# Labeled fixtures (shared by both modes)
# ---------------------------------------------------------------------------
# The labeled fixture (`topic_labels.json`) feeds the categorization,
# summary, and prompt-comparison evals in BOTH stubbed and live mode — only the
# clients differ — so its loader lives outside the mode-specific sections below.


def _labeled_stories() -> tuple[list[Story], dict[str, str]]:
    """Build the labeled stories and `{story_id: expected_topic}` map from the fixture."""
    labeled = load_topic_labels()
    stories = [
        Story(
            id=item.story_id,
            source_item_id=item.source_item_id,
            title=item.title,
            text=item.text,
        )
        for item in labeled
    ]
    labels = {item.story_id: item.expected_topic for item in labeled}
    return stories, labels


def _eval_digest(stories: list[Story], labels: dict[str, str], *, client: LLMClient) -> Digest:
    """Build the `Digest` the summary eval judges, from the labeled stories.

    Groups the stories by their expected topic (the labels define the grouping)
    and summarizes each topic through `summarize_topic` under the production v1
    prompt. The only variable between the two modes is the client: in stubbed
    mode the summarize stage returns the stub's fixed summary string; in live
    mode it returns the real DeepSeek summary — so the summary-quality eval
    judges a real digest in live mode, not a stubbed one.

    This reuses `evals.prompt_comparison`'s `_group_stories_by_label` and
    `_build_digest` helper functions, which already do the grouping and source
    mapping both the summary eval and the prompt-comparison eval need. Both
    evals judge the same shape of digest; the helpers belong to the suite, not
    to one of them.
    """
    topics = _group_stories_by_label(stories, labels)
    return _build_digest(topics, prompt_version=DEFAULT_PROMPT_VERSION, client=client)


# ---------------------------------------------------------------------------
# Stubbed harness
# ---------------------------------------------------------------------------
# One dispatching fake LLM stands in for every stage the evals reach: the digest
# pipeline (segment, cluster, summarize), the RAG answer, and the LLM-as-judge.
# It dispatches by *which known stage prompt* the caller's system message is —
# identity match against the imported prompt objects, not substring match on the
# prompt text. The stubbed runner hands this same fake to every eval's `client=`
# and `judge_client=` seams, so the whole suite runs with no network.
#
# Dispatching on object identity (not on a substring of the prompt) is what
# keeps this robust to edits: rewriting a stage's prompt text changes the
# object both the caller and the stub hold, so dispatch never drifts. The only
# thing that can break it is a stage starting to send a *different* prompt
# object (a new prompt, an interpolation, a concatenation) — a deliberate,
# visible change that already needs new stub handling here.
#
# `_StubLLMClient` subclasses `_ClientBase` (in `protocol.py`) and implements
# `_complete()` to dispatch by stage prompt. The shared `ask()` logic — schema
# prepend, guards, validation — is inherited. The vector-store and embedding
# fakes are reused directly from the test package (`tests.rag.fakes`).

# The known stage prompts the stub dispatches on. `SUMMARIZE_PROMPTS` is a
# versioned registry (v1 and v2 today); both values are stage prompts the
# summarize `eval_prompt_comparison` call sends, so both go in the set. The
# underscore-prefixed names are imported across modules on purpose — the stub
# needs the exact object the caller sends, and importing it is the only way to
# hold the same reference. `tests/evals/test_injection.py` already does this.
_STAGE_PROMPTS: tuple[str, ...] = (
    _SEGMENT_PROMPT,
    _CLUSTER_PROMPT,
    *SUMMARIZE_PROMPTS.values(),
    _RAG_PROMPT,
    _JUDGE_PROMPT,
)


def _completion(content: str) -> ChatCompletion:
    """Build a minimal well-formed `ChatCompletion` for the stub to return."""
    return ChatCompletion(
        id="eval-runner-stub",
        created=0,
        model="eval-runner-stub",
        object="chat.completion",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
    )


def _stage_system(messages: list[Any]) -> str:
    """Return the caller's stage prompt: the system message that equals a known one.

    `parse_structured` prepends its own schema-instruction system message to every
    call, so the stub sees two (or more) system messages. This function finds the
    one that is one of the known stage prompts (`_STAGE_PROMPTS`) by object
    identity — robust to prompt text edits and to changes in the schema
    instruction's wording, since it never looks at that message's text. When the
    caller is a genuinely new stage the stub does not know, this returns ``""``
    and the stub falls back to its benign empty default.
    """
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message["content"]
        if not isinstance(content, str):
            continue
        if content in _STAGE_PROMPTS:
            return content
    return ""


def _first_user(messages: list[Any]) -> str:
    """Return the first user message's content, or an empty string."""
    for message in messages:
        if message.get("role") == "user":
            return str(message["content"])
    return ""


def _first_source_id(user: str) -> str:
    """Pull the first `source: <id>` value out of a summarize user message."""
    for line in user.splitlines():
        if line.startswith("source:"):
            return line.split(":", 1)[1].strip()
    return "unknown.eml"


def _chunk_header(user: str) -> dict[str, Any]:
    """Read the first `[Chunk 0]` header block the RAG user message carries.

    `ask()._format_chunks` writes `digest_date`, `topic_label`, `source_subject`,
    and `chunk_index` as labelled lines under each `[Chunk N]` header. A
    well-behaved stub cites by echoing those labels back, so the answer resolves
    to a real `AugmentedChunk`.
    """
    fields: dict[str, Any] = {
        "digest_date": "2026-06-15",
        "topic_label": "Any",
        "source_subject": "Daily Brief",
        "chunk_index": 0,
    }
    for line in user.splitlines():
        for key in fields:
            prefix = f"{key}: "
            if line.startswith(prefix):
                value: Any = line[len(prefix) :].strip()
                if key == "chunk_index":
                    value = int(value)
                fields[key] = value
        # The first chunk block is all we cite; stop at its `Text:` line.
        if line.startswith("Text:"):
            break
    return fields


class _StubLLMClient(_ClientBase):
    """A dispatching fake client: returns stage-appropriate replies by prompt identity.

    Implements `_complete()` to find the stage prompt in the messages and return
    a well-formed reply for that stage. The dispatch table (`_stub_reply`) is
    eval-specific; the shared `ask()` logic is inherited from `_ClientBase`.
    """

    def _complete(
        self,
        *,
        messages: list[ChatCompletionMessageParam],
        schema: type[BaseModel],
        thinking: bool,
    ) -> ChatCompletion:
        system = _stage_system(messages)
        user = _first_user(messages)
        return _completion(_stub_reply(system, user))


def _stub_reply(system: str, user: str) -> str:
    """Return well-formed JSON for the stage whose prompt *system* identifies.

    Dispatch is by object identity against the imported stage prompts, so a text
    edit to any prompt cannot silently break the stub: the same object is on both
    sides of the comparison. ``_stub_reply`` receives the stage prompt found by
    `_stage_system`; when no known stage prompt is present it returns a benign
    empty default so the stub never crashes an eval.
    """
    if system is _SEGMENT_PROMPT:
        return json.dumps(
            {"stories": [{"title": "Newsletter story", "text": "A faithful passage."}]}
        )
    if system is _CLUSTER_PROMPT:
        # Empty topics → cluster()'s fallback puts each story in its own topic.
        return json.dumps({"topics": []})
    if system in SUMMARIZE_PROMPTS.values():
        return json.dumps(
            {"summary": "A faithful summary of the topic.", "source_ids": [_first_source_id(user)]}
        )
    if system is _RAG_PROMPT:
        return json.dumps(
            {
                "answer": "A faithful answer drawn from the newsletter chunks.",
                "sources": [_chunk_header(user)],
            }
        )
    if system is _JUDGE_PROMPT:
        return RubricScore(
            faithfulness=0.8,
            conciseness=0.7,
            coherence=0.75,
            rationale="Stubbed judge reply.",
        ).model_dump_json()
    # Unknown stage: a benign empty reply so the stub never crashes an eval.
    return json.dumps({"stories": [], "topics": [], "summary": "", "source_ids": []})


def _fixed_embed(value: list[float]) -> EmbedFn:
    """An embed function that returns *value* for every input text."""

    def fn(texts: list[str]) -> list[list[float]]:
        return [list(value) for _ in texts]

    return fn


# A fixed query vector the stubbed RAG probes reuse. Chunks seeded with this
# vector clear the 0.35 confidence threshold so `ask()` reaches the LLM call.
_MATCH_VECTOR: list[float] = [1.0, 0.0, 0.0]


def _injection_chunk_store() -> VectorStore:
    """A `StubStore` seeded with the injection questions' chunks.

    The RAG injection probe needs retrieval to clear the guardrail so `ask()`
    reaches the LLM call where the injected chunk text would take effect. Each
    fixture question carries its own chunk text, source id, and topic label; we
    seed one chunk per question with the match vector so retrieval scores 1.0.
    """
    from tests.rag.fakes import StubStore

    store = StubStore()
    for q in load_injection_questions():
        store.insert(
            [
                IndexChunk(
                    text=q.chunk_text,
                    embedding=_MATCH_VECTOR,
                    metadata={
                        "digest_date": "2026-06-15",
                        "topic_label": q.chunk_topic_label,
                        "source_id": q.chunk_source_id,
                        "source_subject": q.chunk_source_subject,
                        "chunk_index": 0,
                    },
                )
            ]
        )
    return store


# ---------------------------------------------------------------------------
# Live harness
# ---------------------------------------------------------------------------
# In live mode the eval functions get `OpenAIClient.get()` as their client and
# judge, and the RAG evals get the real embedding function and the on-disk Chroma
# store. Nothing here constructs a client eagerly — the eval functions do, on
# their first call, so importing this module never touches the network.


def _live_store() -> VectorStore:
    """The on-disk Chroma store the chat endpoints serve against."""
    from app.rag.chroma_store import ChromaStore

    return ChromaStore()


def _live_embed() -> EmbedFn:
    """The real OpenAI embedding function."""
    from app.rag.embed import embed

    return embed


def _live_injection_chunk_store(embed_fn: EmbedFn) -> VectorStore:
    """A `StubStore` seeded with real embeddings of the injection question chunks.

    In live mode the RAG injection probe must retrieve against chunks whose
    embeddings were computed by the real embedding function, so cosine similarity
    between the real question embedding and the real chunk-text embedding clears
    the 0.35 guardrail and `ask()` reaches the real LLM call.
    """
    from tests.rag.fakes import StubStore

    questions = load_injection_questions()
    texts = [q.chunk_text for q in questions]
    embeddings = embed_fn(texts)

    store = StubStore()
    for q, embedding in zip(questions, embeddings, strict=True):
        store.insert(
            [
                IndexChunk(
                    text=q.chunk_text,
                    embedding=embedding,
                    metadata={
                        "digest_date": "2026-06-15",
                        "topic_label": q.chunk_topic_label,
                        "source_id": q.chunk_source_id,
                        "source_subject": q.chunk_source_subject,
                        "chunk_index": 0,
                    },
                )
            ]
        )
    return store


# ---------------------------------------------------------------------------
# Running the suite
# ---------------------------------------------------------------------------

# Each entry is one eval probe: a display name and a thunk that runs it. The
# thunk closes over the clients/store appropriate to the mode and returns the
# probe's `list[EvalResult]`. Wrapping each thunk in `_run_safe` turns a raised
# exception into a failing `EvalResult` so one probe blowing up never kills the
# run.
_EvalThunk = Callable[[], list[EvalResult]]


def _run_safe(name: str, thunk: _EvalThunk) -> list[EvalResult]:
    """Run one eval thunk, turning any exception into a failing `EvalResult`."""
    try:
        return thunk()
    except Exception as exc:  # noqa: BLE001 — isolate every eval from the rest
        return [
            EvalResult(
                name=name,
                passed=False,
                score=0.0,
                detail=f"ERROR: {exc!r}",
            )
        ]


def _build_evals(*, live: bool) -> list[tuple[str, _EvalThunk]]:
    """Build the (name, thunk) list for the chosen mode.

    Lives in its own function so the stubbed harness is constructed once (the
    same fake client and store serve every eval) and the live harness wires the
    real clients the same way.
    """
    stories, labels = _labeled_stories()
    golden_qa = load_golden_qa()
    injection_items = load_injection_items()

    llm_client: LLMClient
    judge_client: LLMClient
    if live:
        store = _live_store()
        embed_fn = _live_embed()
        llm_client = OpenAIClient.get()
        judge_client = llm_client
        # Live: seed an in-memory store with real embeddings of the injection
        # chunks so retrieval genuinely clears the guardrail and ask() reaches
        # the real LLM call where the injected text would take effect.
        injection_store = _live_injection_chunk_store(embed_fn)
    else:
        from tests.rag.fakes import StubStore

        store = StubStore()
        embed_fn = _fixed_embed(_MATCH_VECTOR)
        stub = _StubLLMClient()
        llm_client = stub
        judge_client = stub
        # Stubbed: the injection probe retrieves from a seeded in-memory store so
        # retrieval clears the guardrail and `ask()` reaches the LLM call where
        # the injected chunk text would take effect.
        injection_store = _injection_chunk_store()

    evals: list[tuple[str, _EvalThunk]] = []

    # Categorization.
    evals.append(
        ("topic_assignment", lambda: eval_topic_assignment(stories, labels, client=llm_client))
    )

    # Summarization (summary quality + judge calibration). The
    # digest the summary eval judges is built through `summarize_topic` under
    # the chosen client: stubbed summaries in CI, real ones on a live run.
    summary_digest = _eval_digest(stories, labels, client=llm_client)
    evals.append(
        ("summary_quality", lambda: eval_summary_quality(summary_digest, judge_client=judge_client))
    )
    evals.append(("judge_calibration", lambda: eval_judge_calibration(judge_client=judge_client)))

    # RAG (retrieval hit rate, answer faithfulness, refusal).
    evals.append(
        (
            "retrieval_hit_rate",
            lambda: eval_retrieval_hit_rate(golden_qa, vector_store=store, embed_fn=embed_fn),
        )
    )
    evals.append(
        (
            "answer_faithfulness",
            lambda: eval_answer_faithfulness(
                golden_qa,
                vector_store=store,
                embed_fn=embed_fn,
                client=llm_client,
                judge_client=judge_client,
            ),
        )
    )
    evals.append(
        ("refusal", lambda: eval_refusal(golden_qa, vector_store=store, embed_fn=embed_fn))
    )

    # Safety/robustness (pipeline + RAG injection).
    evals.append(
        ("pipeline_injection", lambda: eval_pipeline_injection(injection_items, client=llm_client))
    )
    # `injection_store` is the store the RAG injection probe retrieves against;
    # it is bound on both paths above, so this is a plain read with no second
    # conditional to keep a static checker confident it is bound here.
    rag_injection_store = injection_store
    evals.append(
        (
            "rag_injection",
            lambda: eval_rag_injection(
                load_injection_questions(),
                vector_store=rag_injection_store,
                embed_fn=embed_fn,
                client=llm_client,
            ),
        )
    )

    # Prompt-version comparison.
    evals.append(
        (
            "prompt_comparison",
            lambda: eval_prompt_comparison(
                stories, labels, client=llm_client, judge_client=judge_client
            ),
        )
    )

    return evals


def run_all(*, live: bool) -> Scorecard:
    """Run every eval, collect the results into a `Scorecard`.

    Each eval is wrapped so an exception becomes a failing `EvalResult` and the
    next eval still runs. The scorecard's `summary` is the overall pass rate.
    """
    results: list[EvalResult] = []
    for name, thunk in _build_evals(live=live):
        results.extend(_run_safe(name, thunk))

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    rate = passed / total if total else 0.0
    mode = "LIVE" if live else "STUBBED"
    summary = f"{mode} run: {passed}/{total} checks passed ({rate:.3f}). " + (
        "Scored against the real models and the on-disk vector store."
        if live
        else "Stubbed numbers prove wiring only, not that the system works."
    )
    return Scorecard(results=results, summary=summary)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _escape_cell(text: str) -> str:
    """Escape characters that break a markdown table cell (pipes and newlines)."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_scorecard(scorecard: Scorecard, *, live: bool) -> str:
    """Render the scorecard as a markdown table.

    The renderer is deliberately dumb — a fixed table over
    `EvalResult.{name, passed, score, detail}` — so adding an eval later means
    only adding a call in `run_all`, not touching this function.
    """
    header = (
        "# Hedwig eval scorecard (LIVE)\n"
        "\n"
        "Scored against the real DeepSeek LLM, the real OpenAI embeddings, and "
        "the on-disk Chroma store.\n"
        if live
        else "# Hedwig eval scorecard (STUBBED)\n"
        "\n"
        "These numbers are NOT real measurements. The stubbed run only proves "
        "every eval function is wired and returns well-formed results. Run with "
        "--live for the real scorecard.\n"
    )

    lines: list[str] = [
        header.rstrip(),
        "",
        "| Name | Result | Score | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for result in scorecard.results:
        mark = "pass" if result.passed else "fail"
        lines.append(
            f"| {_escape_cell(result.name)} | {mark} | {result.score:.3f} | "
            f"{_escape_cell(result.detail)} |"
        )

    lines.append("")
    lines.append(scorecard.summary)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _is_live(args: argparse.Namespace) -> bool:
    """Live when --live is passed or the env var is set to a truthy value."""
    if args.live:
        return True
    return os.environ.get(_LIVE_ENV, "").strip().lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> int:
    """Parse args, run the suite, print the scorecard, optionally write it to a file."""
    parser = argparse.ArgumentParser(
        prog="evals.run",
        description="Run the Hedwig eval suite and print a markdown scorecard.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Score against the real LLM, embeddings, and vector store (default: stubbed).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Write the scorecard to this file in addition to stdout.",
    )
    args = parser.parse_args(argv)

    live = _is_live(args)
    scorecard = run_all(live=live)
    output = render_scorecard(scorecard, live=live)

    print(output)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
