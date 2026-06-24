"""Tests for `evals.run` — the orchestrator, renderer, and live/stubbed switch.

No real API calls: the stubbed runner wires fake clients/stores through every
eval, and these tests assert the scorecard renders and that the stubbed path
never reaches a real client. Live mode is exercised only to the extent of
confirming the switch flips the header and the clients it would build — the
actual live run is a billable act left to the operator.
"""

from __future__ import annotations

import argparse

import pytest

from evals.run import (
    _is_live,
    _run_safe,
    main,
    render_scorecard,
    run_all,
)
from evals.types import EvalResult, Scorecard

# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_render_includes_header_table_columns_and_summary() -> None:
    """The stubbed scorecard has a STUBBED header, a table, and a summary line."""
    scorecard = Scorecard(
        results=[
            EvalResult(name="topic_assignment", passed=True, score=0.997, detail="3/5"),
            EvalResult(name="retrieval_hit_rate", passed=False, score=0.0, detail="0/5 hits"),
        ],
        summary="STUBBED run: 1/2 checks passed (0.500).",
    )
    output = render_scorecard(scorecard, live=False)

    lines = output.splitlines()
    assert lines[0] == "# Hedwig eval scorecard (STUBBED)"
    assert "NOT real measurements" in output
    # Table header and separator.
    assert "| Name | Result | Score | Detail |" in lines
    assert "| --- | --- | --- | --- |" in lines
    # One row per result, with pass/fail and a 3-decimal score.
    assert any("| topic_assignment | pass | 0.997 | 3/5 |" in line for line in lines)
    assert any("| retrieval_hit_rate | fail | 0.000 | 0/5 hits |" in line for line in lines)
    # The summary line is the last non-empty line.
    assert "STUBBED run: 1/2 checks passed (0.500)." in output


def test_render_live_header_marks_a_live_run() -> None:
    """A live scorecard is headed LIVE so it is never mistaken for a stubbed one."""
    scorecard = Scorecard(results=[], summary="LIVE run: 0/0 checks passed (0.000).")
    output = render_scorecard(scorecard, live=True)
    assert output.startswith("# Hedwig eval scorecard (LIVE)")
    assert "Scored against the real" in output
    # The stubbed disclaimer must NOT appear on a live scorecard.
    assert "NOT real measurements" not in output


def test_render_escapes_pipes_and_newlines_in_detail() -> None:
    """A detail containing a pipe or newline does not break the markdown table."""
    scorecard = Scorecard(
        results=[
            EvalResult(
                name="weird",
                passed=False,
                score=0.0,
                detail="a|b\nc",
            )
        ],
        summary="x",
    )
    output = render_scorecard(scorecard, live=False)
    # The pipe is escaped and the newline flattened to a space inside the cell.
    assert "a\\|b c" in output
    assert "a|b\nc" not in output


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_run_safe_turns_an_exception_into_a_failing_result() -> None:
    """A thunk that raises becomes one failing EvalResult; the error is in detail."""

    def boom() -> list[EvalResult]:
        raise RuntimeError("kaboom")

    results = _run_safe("my_eval", boom)
    assert len(results) == 1
    assert results[0].name == "my_eval"
    assert results[0].passed is False
    assert results[0].score == 0.0
    assert "RuntimeError" in results[0].detail
    assert "kaboom" in results[0].detail


def test_run_safe_passes_through_successful_results() -> None:
    """A thunk that returns results passes them through unchanged."""

    def ok() -> list[EvalResult]:
        return [EvalResult(name="my_eval", passed=True, score=1.0, detail="fine")]

    results = _run_safe("my_eval", ok)
    assert results[0].passed is True
    assert results[0].score == 1.0


# ---------------------------------------------------------------------------
# Stubbed run — wiring and shape, no real clients
# ---------------------------------------------------------------------------

# The aggregate EvalResult names the runner collects from each eval probe.
_EXPECTED_AGGREGATES = {
    "topic_assignment",
    "summary_quality",
    "judge_calibration",
    "retrieval_hit_rate",
    "answer_faithfulness",
    "refusal",
    "pipeline_injection",
    "rag_injection",
    "prompt_comparison",
}


def test_run_all_stubbed_returns_every_eval_aggregate() -> None:
    """The stubbed scorecard carries an aggregate row for every eval probe."""
    scorecard = run_all(live=False)
    names = {r.name for r in scorecard.results}
    missing = _EXPECTED_AGGREGATES - names
    assert not missing, f"Missing eval aggregates: {missing}"


def test_run_all_stubbed_results_are_well_formed() -> None:
    """Every stubbed result has a name, a 0.0–1.0 score, and a non-empty detail."""
    scorecard = run_all(live=False)
    assert scorecard.results, "stubbed run produced no results"
    for result in scorecard.results:
        assert result.name, "result has an empty name"
        assert 0.0 <= result.score <= 1.0
        assert result.detail  # non-empty — the point is the shape, not the value


def test_run_all_stubbed_summary_marks_it_as_stubbed() -> None:
    """The stubbed summary line says STUBBED so it is not read as real numbers."""
    scorecard = run_all(live=False)
    assert scorecard.summary.startswith("STUBBED run:")
    assert "wiring only" in scorecard.summary


def test_run_all_stubbed_never_constructs_a_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --live the runner must never build a real LLM, embedding, or store.

    Patch the real constructors to raise: if the stubbed path reaches any of them,
    the test fails. The stubbed run must still succeed because every eval receives
    a fake client/store/embed function.
    """

    def _no_real(_msg: str = "real client constructed in stubbed mode") -> None:
        raise AssertionError(_msg)

    monkeypatch.setattr("app.llm.client.get_client", _no_real)
    monkeypatch.setattr("app.rag.chroma_store.ChromaStore", _no_real)
    monkeypatch.setattr("app.rag.embed._get_client", _no_real)

    scorecard = run_all(live=False)
    # If we got here, no real client was constructed.
    assert scorecard.results


def test_run_all_stubbed_isolates_a_blowing_up_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One eval raising does not kill the run; it becomes a failing row.

    Patch the categorization eval to raise and assert the rest of the suite still
    ran and the failing eval shows up as an ERROR row.
    """
    import evals.run as runner

    def boom(*_args: object, **_kwargs: object) -> list[EvalResult]:
        raise RuntimeError("categorize blew up")

    monkeypatch.setattr(runner, "eval_topic_assignment", boom)

    scorecard = run_all(live=False)
    names = {r.name for r in scorecard.results}
    # The blown-up eval is a row, and every other eval still ran.
    assert "topic_assignment" in names
    assert _EXPECTED_AGGREGATES - {"topic_assignment"} <= names
    topic_row = next(r for r in scorecard.results if r.name == "topic_assignment")
    assert topic_row.passed is False
    assert "categorize blew up" in topic_row.detail


# ---------------------------------------------------------------------------
# Live/stubbed switch
# ---------------------------------------------------------------------------


def _args(**overrides: bool | str | None) -> argparse.Namespace:
    base: dict[str, bool | str | None] = {"live": False, "out": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def test_is_live_defaults_to_stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEDWIG_EVAL_LIVE", raising=False)
    assert _is_live(_args()) is False


def test_is_live_true_when_live_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEDWIG_EVAL_LIVE", raising=False)
    assert _is_live(_args(live=True)) is True


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes"])
def test_is_live_true_when_env_var_set(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEDWIG_EVAL_LIVE", value)
    assert _is_live(_args()) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "maybe"])
def test_is_live_false_when_env_var_falsy(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEDWIG_EVAL_LIVE", value)
    assert _is_live(_args()) is False


def test_live_flag_overrides_falsy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """--live wins even when the env var is unset/falsy."""
    monkeypatch.delenv("HEDWIG_EVAL_LIVE", raising=False)
    assert _is_live(_args(live=True)) is True


# ---------------------------------------------------------------------------
# main() — stdout, --out, default stubbed
# ---------------------------------------------------------------------------


def test_main_prints_stubbed_scorecard_to_stdout(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main([])` runs the stubbed suite and prints a STUBBED scorecard."""
    monkeypatch.delenv("HEDWIG_EVAL_LIVE", raising=False)
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# Hedwig eval scorecard (STUBBED)")
    assert "| Name | Result | Score | Detail |" in out


def test_main_writes_scorecard_to_out_file(
    tmp_path: object,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--out` writes the scorecard to the file in addition to stdout."""
    import pathlib

    out_path = pathlib.Path(str(tmp_path)) / "scorecard.md"
    monkeypatch.delenv("HEDWIG_EVAL_LIVE", raising=False)
    main(["--out", str(out_path)])
    capsys.readouterr()  # discard stdout
    assert out_path.exists()
    contents = out_path.read_text(encoding="utf-8")
    assert contents.startswith("# Hedwig eval scorecard (STUBBED)")
