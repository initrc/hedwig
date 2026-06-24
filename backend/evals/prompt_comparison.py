"""Prompt-version comparison: run the summary eval under two prompts, show deltas.

The summarization prompt is the thing being regressed. This module treats the
two prompt versions in `app.pipeline.prompts` as first-class artifacts, runs
the summary-quality eval under each on the *same* hand-labeled stories, and
emits the per-version aggregate scores plus an `EvalResult` whose `detail`
states the pass-rate delta (v2 minus v1, per rubric dimension and overall).

It is pure orchestration over the existing summary-quality eval — it does not
write a second judge or a second summary-quality scorer. The only variable
between the two runs is the summarization prompt: both versions summarize the
same topics (grouped from the same labeled stories) and are judged against the
same judge prompt.

Judge determinism
-----------------

The judge is an LLM and can be non-deterministic. The comparison keeps the
labeled set small (a handful of topics) and uses a single judge call per topic
per version. If a live run shows noisy deltas, average a couple of judge runs
per version and record the decision here; the test suite stubs the judge so it
is unaffected.
"""

from __future__ import annotations

import re
from datetime import date

from app.llm.protocol import LLMClient
from app.pipeline.cluster import Topic
from app.pipeline.digest import Digest, DigestSource, DigestTopic
from app.pipeline.prompts import DEFAULT_PROMPT_VERSION, SUMMARIZE_PROMPTS
from app.pipeline.segment import Story
from app.pipeline.summarize import summarize_topic
from evals.summarize import eval_summary_quality
from evals.types import EvalResult

# The two prompt versions compared by default: v1 (the production prompt) and
# v2 (a deliberate variant under regression test). Both must exist in the prompt
# registry. Callers can pass a different pair to `versions`.
PROMPT_VERSIONS: tuple[str, ...] = (DEFAULT_PROMPT_VERSION, "v2")

# Fixed digest date so two runs of this comparison (or a re-run after a prompt
# tweak) produce digests whose only difference is the summary text — the date
# is not a variable. Picked once and pinned, never the clock's "today".
_FIXED_DIGEST_DATE = date(2026, 6, 15)

# Parse the per-dimension averages out of the summary-quality eval's aggregate
# `EvalResult.detail`, which our own code produces in a stable format:
#   "Aggregate over N topics: avg faithfulness=0.70, avg conciseness=0.60,
#    avg coherence=0.80, weighted aggregate=0.65 (faithfulness ×2)."
# Each capture group is the dimension's average (a decimal like 0.70). The
# `,\s*` between dimensions matches the comma plus any whitespace that
# follows it, so the pattern still binds if the detail's line wrapping ever
# changes; `\s*` (zero-or-more whitespace) is more tolerant than a single
# space while still rejecting anything that is not whitespace.
_AGGREGATE_PATTERN = re.compile(
    r"avg faithfulness=([0-9.]+),\s*avg conciseness=([0-9.]+),\s*avg coherence=([0-9.]+)"
)


def _group_stories_by_label(
    stories: list[Story], labels: dict[str, str]
) -> list[Topic]:
    """Group *stories* into `Topic`\\s using the hand-labeled expected topics.

    The human labels define the grouping, so both prompt versions summarize the
    exact same topics — the only variable is the prompt. Stories are kept in
    input order within each topic, and topics appear in first-seen label order
    so the two versions' digests line up topic for topic.
    """
    groups: dict[str, list[Story]] = {}
    order: list[str] = []
    for story in stories:
        label = labels[story.id]
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(story)
    return [Topic(label=label, stories=groups[label]) for label in order]


def _stories_to_sources(stories: list[Story]) -> list[DigestSource]:
    """Turn a topic's stories into the `DigestSource`\\s the judge reads.

    The judge verifies each claim in the summary against the source text, so it
    needs every story that fed the topic — not just the cited ids. `subject` and
    `clean_text` map to the story's title and text, which is the material the
    summarizer was shown.
    """
    return [
        DigestSource(
            id=story.source_item_id,
            # `source` is the sender address in the real pipeline, looked up from
            # the parent `ParsedEmail`. The eval builds a `DigestSource` from a
            # `Story` alone, which does not carry the sender, so we fall back to
            # the source id — a real, traceable identifier rather than a fabricated
            # string. The judge only reads `subject` and `clean_text`, so this
            # value never reaches the prompt.
            source=story.source_item_id,
            subject=story.title,
            original_url=None,
            clean_text=story.text,
        )
        for story in stories
    ]


def _build_digest(
    topics: list[Topic],
    *,
    prompt_version: str,
    client: LLMClient,
) -> Digest:
    """Summarize every *topic* with *prompt_version* and assemble a `Digest`.

    The summary text comes from `summarize_topic` (run under the given prompt
    version); the sources are all the topic's stories, so the judge can check
    faithfulness against everything the summarizer saw.
    """
    digest_topics: list[DigestTopic] = []
    for topic in topics:
        summary = summarize_topic(topic, client=client, prompt_version=prompt_version)
        digest_topics.append(
            DigestTopic(
                label=summary.label,
                summary=summary.summary,
                sources=_stories_to_sources(topic.stories),
            )
        )
    return Digest(date=_FIXED_DIGEST_DATE, topics=digest_topics)


def _aggregate_result(results: list[EvalResult]) -> EvalResult:
    """Return the aggregate `EvalResult` from an `eval_summary_quality` run.

    It is the one whose name is exactly ``"summary_quality"`` (the per-topic
    results are prefixed ``"summary_quality/"``).
    """
    for result in results:
        if result.name == "summary_quality":
            return result
    raise ValueError("eval_summary_quality returned no aggregate result")


def _parse_aggregate_dimensions(detail: str) -> tuple[float, float, float]:
    """Extract (faithfulness, conciseness, coherence) averages from aggregate detail."""
    match = _AGGREGATE_PATTERN.search(detail)
    if match is None:
        raise ValueError(f"Could not parse aggregate dimensions from: {detail!r}")
    return float(match.group(1)), float(match.group(2)), float(match.group(3))


def _pass_rate(results: list[EvalResult]) -> float:
    """Fraction of per-topic summary-quality results that passed.

    A topic passes when its faithfulness is at least 0.5 (the summary-quality
    eval's rule). With no topics, define the pass rate as 1.0 to match that
    eval's empty-digest convention.
    """
    topic_results = [r for r in results if r.name.startswith("summary_quality/")]
    if not topic_results:
        return 1.0
    passed = sum(1 for r in topic_results if r.passed)
    return passed / len(topic_results)


def _version_detail(version: str, aggregate: EvalResult, pass_rate: float) -> str:
    """One-line summary of a version's aggregate score and pass rate."""
    return (
        f"prompt {version}: aggregate score={aggregate.score:.2f}, "
        f"pass rate={pass_rate:.2f}. {aggregate.detail}"
    )


def _delta_detail(
    v1: tuple[float, float, float, float, float],
    v2: tuple[float, float, float, float, float],
    *,
    winner: str,
) -> str:
    """Format the per-dimension and overall deltas (v2 minus v1)."""
    v1_faith, v1_concise, v1_cohere, v1_overall, v1_pass = v1
    v2_faith, v2_concise, v2_cohere, v2_overall, v2_pass = v2
    return (
        f"v2 − v1: "
        f"faithfulness Δ={v2_faith - v1_faith:+.2f}, "
        f"conciseness Δ={v2_concise - v1_concise:+.2f}, "
        f"coherence Δ={v2_cohere - v1_cohere:+.2f}, "
        f"overall Δ={v2_overall - v1_overall:+.2f}; "
        f"pass rate v1={v1_pass:.2f} v2={v2_pass:.2f} (Δ={v2_pass - v1_pass:+.2f}). "
        f"Higher-scoring version: {winner}."
    )


def eval_prompt_comparison(
    stories: list[Story],
    labels: dict[str, str],
    *,
    client: LLMClient,
    judge_client: LLMClient,
    versions: tuple[str, ...] = PROMPT_VERSIONS,
) -> list[EvalResult]:
    """Run `eval_summary_quality` under two prompt versions and report the deltas.

    Parameters
    ----------
    stories:
        The labeled stories to summarize and judge. Build these from the labeled
        fixture the same way `eval_topic_assignment` does.
    labels:
        `{story_id: expected_topic_label}`. The labels define the topic grouping
        so both prompt versions summarize the same topics — the prompt is the
        only variable.
    client:
        The summarize LLM connection. Pass a fake in tests; `None` uses the real
        DeepSeek connection (gated by the runner's ``--live`` flag).
    judge_client:
        The judge LLM connection, passed through to `eval_summary_quality`.
    versions:
        The two prompt versions to compare, in order. Defaults to ``(v1, v2)``.

    Returns
    -------
    list[EvalResult]
        One aggregate result per version (named ``prompt_comparison/<version>``)
        plus a ``prompt_comparison`` result whose `detail` states the per-rubric
        and overall deltas and names the higher-scoring version. The
        ``prompt_comparison`` result passes when the second version scores at
        least as high as the first (no regression).
    """
    if len(versions) != 2:
        raise ValueError("eval_prompt_comparison compares exactly two prompt versions.")
    for version in versions:
        if version not in SUMMARIZE_PROMPTS:
            raise KeyError(f"Unknown prompt version: {version!r}")

    topics = _group_stories_by_label(stories, labels)

    per_version: list[tuple[str, EvalResult, float, float, float, float]] = []
    for version in versions:
        digest = _build_digest(topics, prompt_version=version, client=client)
        results = eval_summary_quality(digest, judge_client=judge_client)
        aggregate = _aggregate_result(results)
        faith, concise, cohere = _parse_aggregate_dimensions(aggregate.detail)
        pass_rate = _pass_rate(results)
        per_version.append((version, aggregate, faith, concise, cohere, pass_rate))

    v1_name, v1_agg, v1_faith, v1_concise, v1_cohere, v1_pass = per_version[0]
    v2_name, v2_agg, v2_faith, v2_concise, v2_cohere, v2_pass = per_version[1]

    winner = v1_name if v1_agg.score >= v2_agg.score else v2_name
    v2_not_a_regression = v2_agg.score >= v1_agg.score

    delta_detail = _delta_detail(
        (v1_faith, v1_concise, v1_cohere, v1_agg.score, v1_pass),
        (v2_faith, v2_concise, v2_cohere, v2_agg.score, v2_pass),
        winner=winner,
    )

    return [
        EvalResult(
            name=f"prompt_comparison/{v1_name}",
            passed=v1_agg.passed,
            score=v1_agg.score,
            detail=_version_detail(v1_name, v1_agg, v1_pass),
        ),
        EvalResult(
            name=f"prompt_comparison/{v2_name}",
            passed=v2_agg.passed,
            score=v2_agg.score,
            detail=_version_detail(v2_name, v2_agg, v2_pass),
        ),
        EvalResult(
            name="prompt_comparison",
            passed=v2_not_a_regression,
            score=v2_agg.score,
            detail=delta_detail,
        ),
    ]


__all__ = ["eval_prompt_comparison"]
