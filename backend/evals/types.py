"""Shared result schema for the eval suite.

Every per-eval function in T0033–T0036 returns `list[EvalResult]`; the runner
(T0037) gathers them into a `Scorecard` and renders it as markdown. The shapes
here are deliberately flat and serializable so the runner needs no per-eval
special-casing.
"""

from pydantic import BaseModel


class EvalResult(BaseModel):
    """One eval check's outcome.

    `score` is a 0.0–1.0 fraction (hit rate, judge rubric average) so the
    scorecard can average across evals of different sizes. `detail` holds a
    short human-readable note (e.g. "3/5 golden sources retrieved", "judge
    drift +0.1 vs human"). Push per-eval specifics into `detail` rather than
    adding fields here, so the runner stays generic.
    """

    name: str
    passed: bool
    score: float
    detail: str = ""


class Scorecard(BaseModel):
    """The whole suite's results, plus a short human-readable summary.

    T0037 builds this from the per-eval `EvalResult` lists and renders it.
    """

    results: list[EvalResult]
    summary: str = ""
