"""Tests for `evals.categorize` — topic-assignment eval with stubbed LLM.

No real API calls: every test injects a `FakeClient` whose reply is a
pre-built `Clustering` JSON so the cluster step runs deterministically.
"""

from evals.categorize import eval_topic_assignment
from tests.fakes import FakeClient, _story, model_reply

# -- perfect grouping --------------------------------------------------------


def test_perfect_grouping_scores_1_0() -> None:
    """When the cluster reproduces the human labels exactly, score is 1.0."""
    from app.pipeline.cluster import Clustering, DraftTopic

    stories = [
        _story("s1", title="AI chip launch", text="A new AI chip was launched."),
        _story("s2", title="Another AI chip", text="Another chip vendor."),
        _story("s3", title="Fed rate cut", text="The Fed cut rates."),
    ]

    # The model's clustering matches the human labels perfectly.
    clustering = Clustering(
        topics=[
            DraftTopic(label="AI hardware", story_ids=["s1", "s2"]),
            DraftTopic(label="Monetary policy", story_ids=["s3"]),
        ]
    )
    client = FakeClient(model_reply(clustering.model_dump_json()))

    result = eval_topic_assignment(
        stories,
        labels={"s1": "ai", "s2": "ai", "s3": "finance"},
        client=client,
    )

    assert len(result) == 1
    assert result[0].name == "topic_assignment"
    assert result[0].score == 1.0
    assert result[0].passed is True


# -- shuffled grouping -------------------------------------------------------


def test_shuffled_grouping_scores_below_1_0() -> None:
    """When the cluster merges stories the human kept apart, score drops."""
    from app.pipeline.cluster import Clustering, DraftTopic

    stories = [
        _story("s1", title="AI chip", text="AI chip launched."),
        _story("s2", title="Fed rates", text="Fed cut rates."),
        _story("s3", title="M&A deal", text="Big merger announced."),
    ]

    # Human says three separate topics; cluster lumps everything into one.
    clustering = Clustering(
        topics=[
            DraftTopic(label="Everything", story_ids=["s1", "s2", "s3"]),
        ]
    )
    client = FakeClient(model_reply(clustering.model_dump_json()))

    result = eval_topic_assignment(
        stories,
        labels={"s1": "ai", "s2": "finance", "s3": "mergers"},
        client=client,
    )

    assert len(result) == 1
    assert result[0].score < 1.0
    # Three separate human topics merged into one: most pairs are wrong.
    # 3 stories → 3 pairs. Human says all pairs are "different" (3 topics).
    # Cluster says all pairs are "same" (1 topic). So 0/3 correct → 0.0.
    assert result[0].score == 0.0


def test_partial_grouping_scores_between_0_and_1() -> None:
    """A mixed case: the cluster gets some pairs right and some wrong."""
    from app.pipeline.cluster import Clustering, DraftTopic

    stories = [
        _story("s1", title="AI chip A", text="Chip A."),
        _story("s2", title="AI chip B", text="Chip B."),
        _story("s3", title="Fed rates", text="Fed."),
        _story("s4", title="M&A", text="Merger."),
    ]

    # Human: s1,s2 = ai; s3 = finance; s4 = mergers (3 topics)
    # Cluster: s1,s2 = ai; s3,s4 = "business" (merges finance+mergers)
    clustering = Clustering(
        topics=[
            DraftTopic(label="AI", story_ids=["s1", "s2"]),
            DraftTopic(label="Business", story_ids=["s3", "s4"]),
        ]
    )
    client = FakeClient(model_reply(clustering.model_dump_json()))

    result = eval_topic_assignment(
        stories,
        labels={"s1": "ai", "s2": "ai", "s3": "finance", "s4": "mergers"},
        client=client,
    )

    assert len(result) == 1
    # 4 stories → 6 pairs.
    # Human same: (s1,s2). Human different: the other 5 pairs.
    # Cluster same: (s1,s2), (s3,s4). Cluster different: the other 4 pairs.
    # Agree on: (s1,s2) same=same ✓, plus 4 pairs where both say different.
    # Disagree on: (s3,s4) — human says different, cluster says same.
    # So 5/6 correct ≈ 0.833
    assert 0.8 < result[0].score < 0.9


# -- edge cases --------------------------------------------------------------


def test_empty_stories_returns_score_1_0() -> None:
    """No stories → no pairs → score 1.0 (vacuously correct)."""
    result = eval_topic_assignment([], labels={})
    assert len(result) == 1
    assert result[0].score == 1.0
    assert result[0].passed is True


def test_single_story_returns_score_1_0() -> None:
    """One story → no pairs to compare → score 1.0."""
    from app.pipeline.cluster import Clustering, DraftTopic

    stories = [_story("s1", title="Solo", text="Only one.")]
    clustering = Clustering(topics=[DraftTopic(label="Solo", story_ids=["s1"])])
    client = FakeClient(model_reply(clustering.model_dump_json()))

    result = eval_topic_assignment(stories, labels={"s1": "whatever"}, client=client)

    assert len(result) == 1
    assert result[0].score == 1.0


# -- detail field content ----------------------------------------------------


def test_detail_reports_topic_counts() -> None:
    """The EvalResult detail mentions the number of human/predicted topics."""
    from app.pipeline.cluster import Clustering, DraftTopic

    stories = [
        _story("s1", title="A", text="a"),
        _story("s2", title="B", text="b"),
    ]
    clustering = Clustering(
        topics=[
            DraftTopic(label="Group", story_ids=["s1", "s2"]),
        ]
    )
    client = FakeClient(model_reply(clustering.model_dump_json()))

    result = eval_topic_assignment(
        stories,
        labels={"s1": "x", "s2": "y"},
        client=client,
    )

    detail = result[0].detail
    assert "2 human topics" in detail
    assert "1 predicted topics" in detail
    assert "2 stories" in detail
