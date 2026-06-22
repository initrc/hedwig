"""Tests for `evals.summarize` — summary-quality eval and judge calibration.

No real API calls: every test injects a `FakeClient` whose reply is a
pre-built `RubricScore` JSON so the judge step runs deterministically.
"""

import json
from pathlib import Path
from typing import cast

import pytest

from evals.summarize import (
    CalibrationItem,
    CalibrationScores,
    CalibrationStory,
    RubricScore,
    eval_judge_calibration,
    eval_summary_quality,
    load_judge_calibration,
)
from tests.fakes import (
    FakeClient,
    _digest,
    _digest_source,
    _digest_topic,
    model_reply,
)


def _judge_client(
    faithfulness: float = 0.9,
    conciseness: float = 0.8,
    coherence: float = 0.85,
    rationale: str = "Looks good.",
) -> FakeClient:
    """Build a fake judge that returns the given rubric scores."""
    score = RubricScore(
        faithfulness=faithfulness,
        conciseness=conciseness,
        coherence=coherence,
        rationale=rationale,
    )
    return FakeClient(model_reply(score.model_dump_json()))


# -- summary quality eval ----------------------------------------------------


def test_single_topic_returns_topic_result_plus_aggregate() -> None:
    """One topic → two EvalResults: the topic and the aggregate."""
    topic = _digest_topic(
        label="AI launches",
        summary="Several AI chips launched.",
        sources=[_digest_source(subject="AI News", clean_text="Chips.")],
    )
    digest = _digest(topics=[topic])

    results = eval_summary_quality(digest, judge_client=_judge_client())

    # One per-topic result + one aggregate = 2 results.
    assert len(results) == 2
    assert results[0].name == "summary_quality/AI launches"
    assert results[1].name == "summary_quality"


def test_per_topic_result_carries_scores_in_detail() -> None:
    """The topic EvalResult detail field includes per-dimension scores."""
    topic = _digest_topic(
        label="Test",
        summary="Test summary.",
        sources=[_digest_source()],
    )
    digest = _digest(topics=[topic])

    results = eval_summary_quality(
        digest, judge_client=_judge_client(faithfulness=0.7, conciseness=0.6, coherence=0.8)
    )

    detail = results[0].detail
    assert "faithfulness=0.70" in detail
    assert "conciseness=0.60" in detail
    assert "coherence=0.80" in detail


def test_weighted_aggregate_favors_faithfulness() -> None:
    """The aggregate score gives faithfulness 2× weight."""
    topic = _digest_topic(
        label="T",
        summary="S.",
        sources=[_digest_source()],
    )
    digest = _digest(topics=[topic])

    results = eval_summary_quality(
        digest,
        judge_client=_judge_client(faithfulness=1.0, conciseness=0.0, coherence=0.0),
    )

    # weighted = (1.0*2 + 0.0 + 0.0) / 4 = 0.5
    assert results[0].score == 0.5

    # Also try when conciseness and coherence are high but faithfulness is low.
    results2 = eval_summary_quality(
        digest,
        judge_client=_judge_client(faithfulness=0.0, conciseness=1.0, coherence=1.0),
    )
    # weighted = (0.0*2 + 1.0 + 1.0) / 4 = 0.5
    assert results2[0].score == 0.5


def test_passed_is_false_when_faithfulness_below_0_5() -> None:
    """A topic fails when faithfulness drops below 0.5."""
    topic = _digest_topic(
        label="Bad summary",
        summary="Invented facts.",
        sources=[_digest_source()],
    )
    digest = _digest(topics=[topic])

    results = eval_summary_quality(
        digest,
        judge_client=_judge_client(faithfulness=0.3),
    )

    assert results[0].passed is False
    # Aggregate also fails because avg faithfulness < 0.5.
    assert results[1].passed is False


def test_multiple_topics_averaged_in_aggregate() -> None:
    """The aggregate result averages across all topics."""
    topics = [
        _digest_topic(label="A", summary="A.", sources=[_digest_source()]),
        _digest_topic(label="B", summary="B.", sources=[_digest_source()]),
    ]
    digest = _digest(topics=topics)

    results = eval_summary_quality(
        digest,
        judge_client=_judge_client(faithfulness=0.8, conciseness=0.6, coherence=0.7),
    )

    # 2 topics + 1 aggregate = 3 results.
    assert len(results) == 3
    # Both topics get the same score (same fake judge reply).
    assert results[0].score == results[1].score
    # Aggregate score should equal the topic score (both topics scored identically).
    assert results[2].score == pytest.approx(results[0].score)


def test_empty_digest_returns_single_result() -> None:
    """No topics → one EvalResult with score 1.0."""
    digest = _digest(topics=[])
    results = eval_summary_quality(digest)
    assert len(results) == 1
    assert results[0].name == "summary_quality"
    assert results[0].score == 1.0
    assert results[0].passed is True


# -- judge calibration -------------------------------------------------------


def _write_calibration_fixture(tmp_path: Path, items: list[CalibrationItem]) -> Path:
    """Write a calibration fixture to *tmp_path* and return its path."""
    path = tmp_path / "judge_calibration.json"
    data = [item.model_dump() for item in items]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_calibration_delta_positive_when_judge_scores_higher(
    tmp_path: Path,
) -> None:
    """Judge scores 0.2 above human → delta is +0.2."""
    item = CalibrationItem(
        topic_label="Test topic",
        summary="A summary.",
        stories=[
            CalibrationStory(title="Story", text="Source text."),
        ],
        human_scores=CalibrationScores(faithfulness=0.7, conciseness=0.6, coherence=0.8),
    )
    fixture = _write_calibration_fixture(tmp_path, [item])

    # Judge returns higher scores than the human.
    judge = _judge_client(faithfulness=0.9, conciseness=0.8, coherence=0.9)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)

    # 1 item + 1 aggregate = 2 results.
    assert len(results) == 2

    item_result = results[0]
    assert item_result.name == "judge_calibration/Test topic"
    assert "faithfulness judge=0.90 human=0.70 Δ=+0.20" in item_result.detail
    assert "conciseness judge=0.80 human=0.60 Δ=+0.20" in item_result.detail
    assert "coherence judge=0.90 human=0.80 Δ=+0.10" in item_result.detail


def test_calibration_delta_negative_when_judge_scores_lower(
    tmp_path: Path,
) -> None:
    """Judge scores below human → delta is negative."""
    item = CalibrationItem(
        topic_label="T",
        summary="S.",
        stories=[CalibrationStory(title="T", text="Text.")],
        human_scores=CalibrationScores(faithfulness=0.9, conciseness=0.9, coherence=0.9),
    )
    fixture = _write_calibration_fixture(tmp_path, [item])

    judge = _judge_client(faithfulness=0.6, conciseness=0.7, coherence=0.8)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)

    item_result = results[0]
    assert "Δ=-0.30" in item_result.detail  # faithfulness delta


def test_calibration_aggregate_reports_mean_deltas(tmp_path: Path) -> None:
    """The aggregate calibration result averages deltas across items."""
    items = [
        CalibrationItem(
            topic_label=f"Topic {i}",
            summary=f"Summary {i}.",
            stories=[CalibrationStory(title="T", text="Text.")],
            human_scores=CalibrationScores(faithfulness=0.8, conciseness=0.7, coherence=0.6),
        )
        for i in range(3)
    ]
    fixture = _write_calibration_fixture(tmp_path, items)

    # Judge scores 0.1 above human on all dimensions for all items.
    judge = _judge_client(faithfulness=0.9, conciseness=0.8, coherence=0.7)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)

    # 3 items + 1 aggregate = 4 results.
    assert len(results) == 4

    agg = results[-1]
    assert agg.name == "judge_calibration"
    assert "faithfulness Δ=+0.10" in agg.detail
    assert "conciseness Δ=+0.10" in agg.detail
    assert "coherence Δ=+0.10" in agg.detail
    assert "Positive = judge scores higher than human" in agg.detail


def test_calibration_passes_when_drift_is_small(tmp_path: Path) -> None:
    """Aggregate passes when max absolute delta < 0.2."""
    item = CalibrationItem(
        topic_label="T",
        summary="S.",
        stories=[CalibrationStory(title="T", text="Text.")],
        human_scores=CalibrationScores(faithfulness=0.8, conciseness=0.8, coherence=0.8),
    )
    fixture = _write_calibration_fixture(tmp_path, [item])

    # Delta of 0.1 on each dimension — within tolerance.
    judge = _judge_client(faithfulness=0.9, conciseness=0.9, coherence=0.9)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)
    assert results[-1].passed is True


def test_calibration_fails_when_drift_is_large(tmp_path: Path) -> None:
    """Aggregate fails when max absolute delta ≥ 0.2."""
    item = CalibrationItem(
        topic_label="T",
        summary="S.",
        stories=[CalibrationStory(title="T", text="Text.")],
        human_scores=CalibrationScores(faithfulness=0.8, conciseness=0.8, coherence=0.8),
    )
    fixture = _write_calibration_fixture(tmp_path, [item])

    # Delta of 0.3 on faithfulness — outside tolerance.
    judge = _judge_client(faithfulness=0.5, conciseness=0.9, coherence=0.9)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)
    assert results[-1].passed is False


def test_load_calibration_missing_file_raises() -> None:
    """Loading a nonexistent fixture raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_judge_calibration(Path("/nonexistent/calibration.json"))


def test_calibration_item_score_bounded_at_zero(tmp_path: Path) -> None:
    """Score is clamped at 0.0 even when delta > 1.0."""
    item = CalibrationItem(
        topic_label="T",
        summary="S.",
        stories=[CalibrationStory(title="T", text="Text.")],
        human_scores=CalibrationScores(faithfulness=1.0, conciseness=1.0, coherence=1.0),
    )
    fixture = _write_calibration_fixture(tmp_path, [item])

    # Judge scores 0.0 vs human 1.0 → delta = -1.0.
    judge = _judge_client(faithfulness=0.0, conciseness=0.0, coherence=0.0)

    results = eval_judge_calibration(judge_client=judge, calibration_path=fixture)
    # 1 - abs(-1.0) = 0.0, not negative.
    assert results[0].score == 0.0


# -- judge prompt contains source material -----------------------------------


def test_judge_receives_source_text() -> None:
    """The judge prompt includes the source story text so it can verify claims."""
    topic = _digest_topic(
        label="Test",
        summary="The summary.",
        sources=[
            _digest_source(
                subject="Newsletter A",
                clean_text="A new GPU launched today with 2× performance.",
            ),
        ],
    )
    digest = _digest(topics=[topic])

    judge = _judge_client()
    eval_summary_quality(digest, judge_client=judge)

    # The fake records what was sent to the model.
    messages = judge.chat.completions.messages
    # Cast through dict to avoid TypedDict union indexing issues — the same
    # pattern used by schema_instruction() in tests/fakes.py.
    dicts = cast("list[dict[str, object]]", messages)
    user_msg = [m for m in dicts if m.get("role") == "user"][0]
    user_content = str(user_msg["content"])
    assert "A new GPU launched today with 2× performance." in user_content
    assert "Newsletter A" in user_content
    assert "The summary." in user_content
