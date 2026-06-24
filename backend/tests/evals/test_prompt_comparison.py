"""Tests for `evals.prompt_comparison` — prompt-version deltas without real API calls.

Both the summarize LLM and the judge LLM are stubbed with queued fakes: the
summarize fake returns a fixed `DraftSummary` per topic per version (in call
order), and the judge fake returns a fixed `RubricScore` per topic per version.
So the comparison runs fully deterministically and the deltas can be checked by
hand.
"""

from typing import cast

from app.llm.fake_client import FakeClient, QueuedFakeClient, model_reply
from app.pipeline.prompts import (
    DEFAULT_PROMPT_VERSION,
    SUMMARIZE_PROMPTS,
    get_summarize_prompt,
)
from app.pipeline.summarize import DraftSummary, summarize_topic
from evals.prompt_comparison import eval_prompt_comparison
from evals.summarize import RubricScore
from evals.types import EvalResult
from tests.fakes import make_story as story


def _draft_json(summary: str, source_id: str) -> str:
    return DraftSummary(summary=summary, source_ids=[source_id]).model_dump_json()


def _rubric_json(faith: float, concise: float, cohere: float) -> str:
    return RubricScore(
        faithfulness=faith,
        conciseness=concise,
        coherence=cohere,
        rationale="stub",
    ).model_dump_json()


# -- the comparison ----------------------------------------------------------


def test_comparison_reports_per_version_aggregates_and_delta() -> None:
    """Two versions → three EvalResults: v1, v2, and the delta."""
    stories = [
        story("a#0", source_item_id="a.eml", title="A", text="A text."),
        story("b#0", source_item_id="b.eml", title="B", text="B text."),
    ]
    labels = {"a#0": "Topic A", "b#0": "Topic B"}

    # Summarize calls happen in order: v1/A, v1/B, v2/A, v2/B.
    summarize_client = QueuedFakeClient(
        [
            model_reply(_draft_json("v1 summary A", "a.eml")),
            model_reply(_draft_json("v1 summary B", "b.eml")),
            model_reply(_draft_json("v2 summary A", "a.eml")),
            model_reply(_draft_json("v2 summary B", "b.eml")),
        ]
    )
    # Judge calls happen in the same order: v1/A, v1/B, v2/A, v2/B.
    judge_client = QueuedFakeClient(
        [
            model_reply(_rubric_json(0.6, 0.5, 0.5)),  # v1 A: passes (faith ≥ 0.5)
            model_reply(_rubric_json(0.4, 0.5, 0.5)),  # v1 B: fails
            model_reply(_rubric_json(0.9, 0.8, 0.8)),  # v2 A
            model_reply(_rubric_json(0.8, 0.7, 0.7)),  # v2 B
        ]
    )

    results = eval_prompt_comparison(
        stories, labels, client=summarize_client, judge_client=judge_client
    )

    assert [r.name for r in results] == [
        "prompt_comparison/v1",
        "prompt_comparison/v2",
        "prompt_comparison",
    ]

    v1, v2, delta = results

    # v1 avg: faith=0.5, concise=0.5, cohere=0.5 → weighted=(1.0+0.5+0.5)/4=0.5
    assert v1.score == 0.5
    # v1 pass rate = 1/2
    assert "pass rate=0.50" in v1.detail

    # v2 avg: faith=0.85, concise=0.75, cohere=0.75 → weighted=(1.7+0.75+0.75)/4=0.8
    assert v2.score == 0.8
    assert "pass rate=1.00" in v2.detail

    # Deltas: faith +0.35, concise +0.25, cohere +0.25, overall +0.30, pass +0.50.
    assert "faithfulness Δ=+0.35" in delta.detail
    assert "conciseness Δ=+0.25" in delta.detail
    assert "coherence Δ=+0.25" in delta.detail
    assert "overall Δ=+0.30" in delta.detail
    assert "pass rate v1=0.50 v2=1.00 (Δ=+0.50)" in delta.detail
    assert "Higher-scoring version: v2." in delta.detail

    # v2 scored higher → no regression → the delta result passes.
    assert delta.passed is True
    assert delta.score == 0.8


def test_comparison_marks_regression_when_v2_scores_lower() -> None:
    """When v2 scores below v1, the delta result fails and names v1 as winner."""
    stories = [
        story("a#0", source_item_id="a.eml", title="A", text="A text."),
    ]
    labels = {"a#0": "Topic A"}

    summarize_client = QueuedFakeClient(
        [
            model_reply(_draft_json("v1 summary A", "a.eml")),
            model_reply(_draft_json("v2 summary A", "a.eml")),
        ]
    )
    judge_client = QueuedFakeClient(
        [
            model_reply(_rubric_json(0.9, 0.8, 0.8)),  # v1 strong
            model_reply(_rubric_json(0.4, 0.5, 0.5)),  # v2 weak (fails)
        ]
    )

    results = eval_prompt_comparison(
        stories, labels, client=summarize_client, judge_client=judge_client
    )

    v1, v2, delta = results
    assert v1.score > v2.score
    assert delta.passed is False  # v2 is a regression
    assert "Higher-scoring version: v1." in delta.detail
    # faithfulness delta = 0.4 - 0.9 = -0.50
    assert "faithfulness Δ=-0.50" in delta.detail


def test_comparison_rejects_unknown_version() -> None:
    """An unknown prompt version raises KeyError before any LLM call."""
    stories = [story("a#0", source_item_id="a.eml", title="A", text="A.")]
    labels = {"a#0": "Topic A"}
    import pytest

    with pytest.raises(KeyError):
        eval_prompt_comparison(
            stories, labels, versions=("v1", "nope"),
            client=FakeClient(model_reply("{}")),
            judge_client=FakeClient(model_reply("{}")),
        )


def test_comparison_requires_exactly_two_versions() -> None:
    import pytest

    stories = [story("a#0", source_item_id="a.eml", title="A", text="A.")]
    labels = {"a#0": "Topic A"}
    with pytest.raises(ValueError):
        eval_prompt_comparison(
            stories, labels, versions=("v1",),
            client=FakeClient(model_reply("{}")),
            judge_client=FakeClient(model_reply("{}")),
        )


# -- prompt registry wiring in summarize_topic --------------------------------


def test_summarize_topic_default_uses_v1_prompt() -> None:
    """Omitting prompt_version sends the v1 system prompt to the model."""
    topic_story = story("a#0", source_item_id="a.eml", title="A", text="A.")
    from tests.fakes import make_topic

    topic = make_topic("Topic A", stories=[topic_story])
    client = FakeClient(model_reply(_draft_json("s", "a.eml")))

    summarize_topic(topic, client=client)

    # parse_structured prepends its own schema-instruction system message, so the
    # summarization prompt is the *second* system message — find it by content.
    messages = cast("list[dict[str, object]]", client.messages)
    system_contents = [
        str(m["content"]) for m in messages if m.get("role") == "system"
    ]
    assert SUMMARIZE_PROMPTS["v1"] in system_contents


def test_summarize_topic_v2_sends_v2_prompt() -> None:
    """prompt_version='v2' sends the v2 system prompt, which differs from v1."""
    topic_story = story("a#0", source_item_id="a.eml", title="A", text="A.")
    from tests.fakes import make_topic

    topic = make_topic("Topic A", stories=[topic_story])
    client = FakeClient(model_reply(_draft_json("s", "a.eml")))

    summarize_topic(topic, client=client, prompt_version="v2")

    messages = cast("list[dict[str, object]]", client.messages)
    system_contents = [
        str(m["content"]) for m in messages if m.get("role") == "system"
    ]
    assert SUMMARIZE_PROMPTS["v2"] in system_contents
    assert SUMMARIZE_PROMPTS["v1"] not in system_contents


# -- prompt registry itself ---------------------------------------------------


def test_default_prompt_version_is_v1() -> None:
    assert DEFAULT_PROMPT_VERSION == "v1"


def test_get_summarize_prompt_unknown_version_raises() -> None:
    import pytest

    with pytest.raises(KeyError):
        get_summarize_prompt("nope")


def test_v2_prompt_differs_from_v1_and_keeps_citation_instruction() -> None:
    """v2 is a deliberate variant but still tells the model to cite by id."""
    v1 = SUMMARIZE_PROMPTS["v1"]
    v2 = SUMMARIZE_PROMPTS["v2"]
    assert v1 != v2
    # The citation instruction is the part the code-enforced check relies on;
    # both versions must keep it so citation ids still come back.
    assert "only ids that appear in the input" in v1
    assert "only ids that appear in the input" in v2


def test_prompt_comparison_results_are_eval_results() -> None:
    """Sanity: the comparison returns EvalResult instances."""
    stories = [story("a#0", source_item_id="a.eml", title="A", text="A.")]
    labels = {"a#0": "Topic A"}
    summarize_client = QueuedFakeClient(
        [model_reply(_draft_json("v1 A", "a.eml")), model_reply(_draft_json("v2 A", "a.eml"))]
    )
    judge_client = QueuedFakeClient(
        [model_reply(_rubric_json(0.7, 0.7, 0.7)), model_reply(_rubric_json(0.8, 0.8, 0.8))]
    )

    results = eval_prompt_comparison(
        stories, labels, client=summarize_client, judge_client=judge_client
    )

    assert all(isinstance(r, EvalResult) for r in results)
