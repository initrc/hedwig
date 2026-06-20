"""Tests for the shared eval result schema (`app.evals.types`)."""

from evals.types import EvalResult, Scorecard


def test_eval_result_defaults_detail_to_empty() -> None:
    result = EvalResult(name="retrieval_hit_rate", passed=True, score=1.0)
    assert result.detail == ""


def test_eval_result_round_trips_through_json() -> None:
    result = EvalResult(name="topic_accuracy", passed=False, score=0.4, detail="2/5")
    rebuilt = EvalResult.model_validate_json(result.model_dump_json())
    assert rebuilt == result


def test_scorecard_holds_results_and_summary() -> None:
    results = [
        EvalResult(name="a", passed=True, score=1.0),
        EvalResult(name="b", passed=False, score=0.0, detail="refusal fired"),
    ]
    scorecard = Scorecard(results=results, summary="1/2 passed")
    assert len(scorecard.results) == 2
    assert scorecard.summary == "1/2 passed"
    assert scorecard.results[1].detail == "refusal fired"


def test_scorecard_defaults_summary_to_empty() -> None:
    scorecard = Scorecard(results=[])
    assert scorecard.summary == ""
    assert scorecard.results == []


def test_scorecard_round_trips_through_json() -> None:
    scorecard = Scorecard(
        results=[EvalResult(name="a", passed=True, score=0.8, detail="ok")],
        summary="all good",
    )
    rebuilt = Scorecard.model_validate_json(scorecard.model_dump_json())
    assert rebuilt == scorecard
