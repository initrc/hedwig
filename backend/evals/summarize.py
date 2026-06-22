"""Summary-quality eval via LLM-as-judge against a faithfulness/conciseness/coherence rubric.

Each topic summary is scored by an LLM judge on three dimensions:

* **faithfulness** — every claim traceable to the source text (no invented facts).
  This is the most important dimension and is weighted 2× in the aggregate.
* **conciseness** — tight, no wasted words, no repetition.
* **coherence** — unified paragraph, logical flow, good transitions.

The judge returns per-dimension scores (0.0–1.0) plus a rationale. These are
aggregated into per-topic `EvalResult`\\s and an overall aggregate.

Judge calibration
-----------------

A separate `eval_judge_calibration()` function loads a hand-scored fixture
(`fixtures/judge_calibration.json`) and runs the judge on the same summaries,
then reports the per-dimension delta (judge minus human). This is what
"understand judge drift" means in practice — a number on the scorecard, not a
vibe. Positive delta means the judge scores higher than the human.

The calibration fixture is hand-written by a human; there is a skeleton at
`fixtures/judge_calibration.skeleton.json` showing the schema.
"""

from pathlib import Path

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, TypeAdapter

from app.llm.client import LLMClient, parse_structured
from app.pipeline.digest import Digest, DigestSource, DigestTopic
from evals.types import EvalResult

# ---------------------------------------------------------------------------
# Judge schema — the structured output the LLM judge must return
# ---------------------------------------------------------------------------


class RubricScore(BaseModel):
    """The judge's scores for one summary on three dimensions.

    Each dimension is 0.0 (worst) to 1.0 (best). The `rationale` must point to
    specific claims that raised or lowered the faithfulness score, quoting the
    source text that supports or contradicts them.
    """

    faithfulness: float
    conciseness: float
    coherence: float
    rationale: str


# ---------------------------------------------------------------------------
# Calibration fixture schema
# ---------------------------------------------------------------------------


class CalibrationStory(BaseModel):
    """One source story inside a calibration entry."""

    title: str
    text: str


class CalibrationScores(BaseModel):
    """Human-assigned scores for one summary."""

    faithfulness: float
    conciseness: float
    coherence: float
    notes: str = ""


class CalibrationItem(BaseModel):
    """One hand-scored summary used to measure judge drift."""

    topic_label: str
    summary: str
    stories: list[CalibrationStory]
    human_scores: CalibrationScores


# ---------------------------------------------------------------------------
# Judge prompt — the learning core; iterate this against the calibration
# fixture to reduce judge drift, especially on faithfulness.
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of news digest summaries. You score each summary "
    "on three dimensions, each 0.0 (worst) to 1.0 (best).\n\n"
    "FAITHFULNESS: Is every claim in the summary directly backed by the source "
    "stories? If the summary says something the sources do not say, deduct. "
    "If it invents numbers, names, or events not in the sources, score low. "
    "A score of 1.0 means every factual claim traces cleanly to the source text.\n\n"
    "CONCISENESS: Is the summary tight and efficient? No repetition, no filler "
    "phrases, no irrelevant asides. A score of 1.0 means every word earns its "
    "place and nothing can be cut without losing substance.\n\n"
    "COHERENCE: Does the summary read as one unified paragraph with logical "
    "flow? Good transitions, clear connection between sentences. A score of 1.0 "
    "means it flows naturally from start to finish. A score of 0.0 means it "
    "reads like unrelated bullet points glued together.\n\n"
    "Be strict. Most summaries should score in the 0.5–0.9 range. Reserve 1.0 "
    "for nearly perfect output. In your rationale, point to specific claims that "
    "raised or lowered the faithfulness score, and quote the source text that "
    "supports or contradicts them."
)


def _judge_user_prompt(topic: DigestTopic) -> str:
    """Build the user prompt: source stories then the summary to judge.

    Each source is shown with its subject line and full body text so the judge
    can verify every claim in the summary against the original material.
    """
    blocks: list[str] = []
    for i, source in enumerate(topic.sources, start=1):
        blocks.append(f"SOURCE {i}: {source.subject}\n{source.clean_text}")

    source_text = "\n\n---\n\n".join(blocks)

    return (
        f"SOURCE STORIES:\n\n{source_text}\n\n"
        f"---\n\n"
        f"SUMMARY TO EVALUATE (topic: {topic.label}):\n\n{topic.summary}"
    )


def _judge_topic(
    topic: DigestTopic,
    *,
    judge_client: LLMClient | None = None,
) -> RubricScore:
    """Run the judge on one topic's summary and return its structured scores."""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": _judge_user_prompt(topic)},
    ]
    return parse_structured(
        messages=messages,
        schema=RubricScore,
        client=judge_client,
    )


# ---------------------------------------------------------------------------
# Main eval function
# ---------------------------------------------------------------------------


def _weighted_aggregate(faithfulness: float, conciseness: float, coherence: float) -> float:
    """Combine the three dimensions into one score, weighting faithfulness 2×.

    Faithfulness matters most because an invented fact is worse than a wordy or
    choppy summary — it actively misleads the reader. Conciseness and coherence
    each get weight 1, so faithfulness counts for half the aggregate.
    """
    return (faithfulness * 2 + conciseness + coherence) / 4


def eval_summary_quality(
    digest: Digest,
    *,
    judge_client: LLMClient | None = None,
) -> list[EvalResult]:
    """Score every topic summary in *digest* via LLM-as-judge.

    Returns one `EvalResult` per topic (name prefixed `summary_quality/`)
    plus an aggregate `EvalResult` named `summary_quality`. Each topic
    result carries the per-dimension scores and the judge's rationale in its
    `detail` field.

    The aggregate score is the mean of the per-topic weighted aggregates
    (faithfulness ×2, conciseness ×1, coherence ×1, divided by 4).
    """
    if not digest.topics:
        return [
            EvalResult(
                name="summary_quality",
                passed=True,
                score=1.0,
                detail="No topics to evaluate.",
            )
        ]

    results: list[EvalResult] = []
    faith_scores: list[float] = []
    concise_scores: list[float] = []
    cohere_scores: list[float] = []

    for topic in digest.topics:
        rubric = _judge_topic(topic, judge_client=judge_client)

        weighted = _weighted_aggregate(rubric.faithfulness, rubric.conciseness, rubric.coherence)

        faith_scores.append(rubric.faithfulness)
        concise_scores.append(rubric.conciseness)
        cohere_scores.append(rubric.coherence)

        # A topic fails when faithfulness — the dimension that matters most —
        # drops below 0.5, meaning the summary likely invents facts.
        results.append(
            EvalResult(
                name=f"summary_quality/{topic.label}",
                passed=rubric.faithfulness >= 0.5,
                score=weighted,
                detail=(
                    f"faithfulness={rubric.faithfulness:.2f} "
                    f"conciseness={rubric.conciseness:.2f} "
                    f"coherence={rubric.coherence:.2f} "
                    f"(weighted aggregate={weighted:.2f}, faithfulness ×2). "
                    f"Rationale: {rubric.rationale}"
                ),
            )
        )

    # Build the aggregate across all topics.
    n = len(digest.topics)
    avg_faith = sum(faith_scores) / n
    avg_concise = sum(concise_scores) / n
    avg_cohere = sum(cohere_scores) / n
    avg_weighted = _weighted_aggregate(avg_faith, avg_concise, avg_cohere)

    results.append(
        EvalResult(
            name="summary_quality",
            passed=avg_faith >= 0.5,
            score=avg_weighted,
            detail=(
                f"Aggregate over {n} topics: "
                f"avg faithfulness={avg_faith:.2f}, "
                f"avg conciseness={avg_concise:.2f}, "
                f"avg coherence={avg_cohere:.2f}, "
                f"weighted aggregate={avg_weighted:.2f} "
                f"(faithfulness ×2)."
            ),
        )
    )

    return results


# ---------------------------------------------------------------------------
# Judge calibration — compare the judge to human scores
# ---------------------------------------------------------------------------

_DEFAULT_CALIBRATION_PATH = Path(__file__).resolve().parent / "fixtures" / "judge_calibration.json"


def load_judge_calibration(
    path: Path | None = None,
) -> list[CalibrationItem]:
    """Load the hand-scored calibration fixture.

    Raises `FileNotFoundError` when the fixture does not exist (the human has
    not written it yet). The caller should catch this and skip calibration.
    """
    target = path or _DEFAULT_CALIBRATION_PATH
    data = target.read_text(encoding="utf-8")
    adapter: TypeAdapter[list[CalibrationItem]] = TypeAdapter(list[CalibrationItem])
    return adapter.validate_json(data)


def _calibration_topic(item: CalibrationItem) -> DigestTopic:
    """Build a `DigestTopic` from a calibration entry.

    The stories in the fixture become `DigestSource` objects so `_judge_topic`
    can consume them through the same path as real digest topics.
    """
    sources = [
        DigestSource(
            id=f"calib-{i}",
            source="calibration",
            subject=story.title,
            original_url=None,
            clean_text=story.text,
        )
        for i, story in enumerate(item.stories)
    ]
    return DigestTopic(
        label=item.topic_label,
        summary=item.summary,
        sources=sources,
    )


def eval_judge_calibration(
    *,
    judge_client: LLMClient | None = None,
    calibration_path: Path | None = None,
) -> list[EvalResult]:
    """Run the judge on the hand-scored calibration summaries and report drift.

    Returns one `EvalResult` per calibration item (name prefixed
    `judge_calibration/`) plus an aggregate `EvalResult` named
    `judge_calibration`. The aggregate detail shows the mean per-dimension
    delta (judge minus human).

    Positive delta → judge scores higher than the human (optimistic).
    Negative delta → judge scores lower than the human (pessimistic).
    """
    items = load_judge_calibration(calibration_path)

    results: list[EvalResult] = []
    faith_deltas: list[float] = []
    concise_deltas: list[float] = []
    cohere_deltas: list[float] = []

    for item in items:
        topic = _calibration_topic(item)
        rubric = _judge_topic(topic, judge_client=judge_client)
        human = item.human_scores

        faith_delta = rubric.faithfulness - human.faithfulness
        concise_delta = rubric.conciseness - human.conciseness
        cohere_delta = rubric.coherence - human.coherence

        faith_deltas.append(faith_delta)
        concise_deltas.append(concise_delta)
        cohere_deltas.append(cohere_delta)

        detail = (
            f"{item.topic_label}: "
            f"faithfulness judge={rubric.faithfulness:.2f} human={human.faithfulness:.2f} "
            f"Δ={faith_delta:+.2f}, "
            f"conciseness judge={rubric.conciseness:.2f} human={human.conciseness:.2f} "
            f"Δ={concise_delta:+.2f}, "
            f"coherence judge={rubric.coherence:.2f} human={human.coherence:.2f} "
            f"Δ={cohere_delta:+.2f}"
        )

        results.append(
            EvalResult(
                name=f"judge_calibration/{item.topic_label}",
                passed=abs(faith_delta) < 0.3,
                score=max(0.0, 1.0 - abs(faith_delta)),
                detail=detail,
            )
        )

    n = len(items)
    mean_faith = sum(faith_deltas) / n
    mean_concise = sum(concise_deltas) / n
    mean_cohere = sum(cohere_deltas) / n

    # The calibration as a whole passes when no mean dimension drifts by ≥ 0.2.
    max_abs = max(abs(mean_faith), abs(mean_concise), abs(mean_cohere))
    results.append(
        EvalResult(
            name="judge_calibration",
            passed=max_abs < 0.2,
            score=max(0.0, 1.0 - max_abs),
            detail=(
                f"Mean judge drift over {n} calibration items: "
                f"faithfulness Δ={mean_faith:+.2f}, "
                f"conciseness Δ={mean_concise:+.2f}, "
                f"coherence Δ={mean_cohere:+.2f}. "
                f"Positive = judge scores higher than human."
            ),
        )
    )

    return results
