"""Topic-assignment eval: score how well `cluster()` matches human-labeled topics.

The metric is **pairwise co-membership accuracy** — the Rand index without
adjustment, chosen because it is simple to explain and catches the two failure
modes we care about (over-merging and over-splitting) without needing a library.

For every pair of stories we check whether the human and the cluster agree on
whether they belong together. The score is the fraction of pairs where they agree.

Formula
-------

Let N = number of stories.

* H(i, j) = 1 when the human put stories i and j in the same topic, 0 otherwise.
* C(i, j) = 1 when `cluster()` put stories i and j in the same topic, 0 otherwise.

::

    correct = count of pairs where H(i,j) == C(i,j)
    total   = N * (N − 1) / 2
    score   = correct / total      (1.0 when total == 0, i.e. N < 2)

The label strings themselves are never compared — cluster labels are free-form
LLM text — so the metric is blind to whether the LLM named a topic "AI launches"
or "artificial intelligence releases". It only checks that stories the human
grouped together stay together and stories the human separated stay separate.
"""

from app.llm.protocol import LLMClient
from app.pipeline.cluster import Topic, cluster
from app.pipeline.segment import Story
from evals.types import EvalResult


def _build_label_map(topics: list[Topic]) -> dict[str, str]:
    """Return `{story_id: topic_label}` for every story in *topics*.

    Every story is in exactly one topic (`cluster` guarantees this), so the
    mapping is total over the input stories. When a story appears in more than
    one topic (should not happen), the last-seen label wins.
    """
    mapping: dict[str, str] = {}
    for topic in topics:
        for story in topic.stories:
            mapping[story.id] = topic.label
    return mapping


def _pairwise_accuracy(
    predicted: dict[str, str],
    expected: dict[str, str],
    story_ids: list[str],
) -> float:
    """Compute pairwise co-membership accuracy for *story_ids*.

    Each pair contributes 1 when the human and the cluster agree (both say "same
    topic" or both say "different topic") and 0 otherwise.
    """
    n = len(story_ids)
    if n < 2:
        return 1.0

    correct = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = story_ids[i], story_ids[j]
            human_same = expected.get(a) == expected.get(b)
            cluster_same = predicted.get(a) == predicted.get(b)
            if human_same == cluster_same:
                correct += 1
            total += 1

    return correct / total


def eval_topic_assignment(
    stories: list[Story],
    labels: dict[str, str],
    *,
    client: LLMClient,
) -> list[EvalResult]:
    """Run `cluster()` on *stories* and score against hand-labeled expected topics.

    Parameters
    ----------
    stories:
        The stories to cluster (the same `Story` objects the pipeline feeds to
        `cluster()`). Build these from the labeled fixture's `story_id`,
        `source_item_id`, `title`, and `text` fields.
    labels:
        `{story_id: expected_topic_label}` from the human annotation. Keys
        must cover every story id in *stories*.
    client:
        Pass a fake client in tests; `None` uses the real DeepSeek connection.

    Returns
    -------
    list[EvalResult]
        A single-element list with the pairwise co-membership accuracy score.
        The `detail` field reports the number of human topics, predicted
        topics, and stories so the scorecard reader can judge coverage at a
        glance.
    """
    topics = cluster(stories, client=client)
    predicted = _build_label_map(topics)

    story_ids = [s.id for s in stories]
    score = _pairwise_accuracy(predicted, labels, story_ids)

    n_predicted = len(topics)
    n_expected = len(set(labels.values()))

    return [
        EvalResult(
            name="topic_assignment",
            passed=score >= 0.5,
            score=score,
            detail=(
                f"Pairwise co-membership accuracy: {score:.3f} "
                f"({n_expected} human topics, "
                f"{n_predicted} predicted topics, "
                f"{len(story_ids)} stories)"
            ),
        )
    ]
