"""Tests for `app.pipeline.cluster`, the story-grouping step.

These never reach the network or spend money. Each test hands `cluster` a
`FakeClient` (from `tests.fakes`) in place of the real Groq connection: the fake
remembers the request it was given and replies with a fixed answer. So we control
what "the model returned" and check that `cluster` builds the right prompt, asks
for the `Clustering` shape, and resolves the returned ids back into `Topic`
objects — keeping the mapping from input stories to topics total and honest no
matter what the model says.
"""

from typing import cast

from app.pipeline.cluster import Clustering, DraftTopic, cluster
from app.pipeline.segment import Story
from tests.fakes import FakeClient, model_reply


def _fake_client(*drafts: DraftTopic) -> FakeClient:
    """A fake client whose reply groups the stories exactly into these topics."""
    return FakeClient(model_reply(Clustering(topics=list(drafts)).model_dump_json()))


def _story(story_id: str, title: str = "Title", text: str = "Body text.") -> Story:
    """A minimal `Story` for a clustering test."""
    return Story(id=story_id, source_item_id="news.eml", title=title, text=text)


def test_related_stories_land_in_one_topic() -> None:
    stories = [
        _story("a#0", "Acme raises $50M"),
        _story("a#1", "Acme funding round led by Foo Capital"),
    ]
    client = _fake_client(DraftTopic(label="Acme funding", story_ids=["a#0", "a#1"]))

    topics = cluster(stories, client=client)

    assert len(topics) == 1
    assert topics[0].label == "Acme funding"
    assert [s.id for s in topics[0].stories] == ["a#0", "a#1"]


def test_unrelated_stories_split_into_separate_topics() -> None:
    stories = [_story("a#0", "Chip launch"), _story("b#0", "Bond market dips")]
    client = _fake_client(
        DraftTopic(label="Chips", story_ids=["a#0"]),
        DraftTopic(label="Bonds", story_ids=["b#0"]),
    )

    topics = cluster(stories, client=client)

    assert [t.label for t in topics] == ["Chips", "Bonds"]
    assert [[s.id for s in t.stories] for t in topics] == [["a#0"], ["b#0"]]


def test_every_topic_story_traces_back_to_an_input_story() -> None:
    stories = [_story("a#0"), _story("a#1"), _story("b#0")]
    client = _fake_client(
        DraftTopic(label="One", story_ids=["a#0", "a#1"]),
        DraftTopic(label="Two", story_ids=["b#0"]),
    )

    topics = cluster(stories, client=client)

    inputs_by_id = {s.id: s for s in stories}
    for topic in topics:
        for story in topic.stories:
            assert inputs_by_id[story.id] is story


def test_mapping_is_total_every_input_story_lands_in_exactly_one_topic() -> None:
    stories = [_story("a#0"), _story("a#1"), _story("b#0")]
    # The model groups two and forgets the third entirely.
    client = _fake_client(DraftTopic(label="Pair", story_ids=["a#0", "a#1"]))

    topics = cluster(stories, client=client)

    placed = [s.id for t in topics for s in t.stories]
    # Every input id appears once and only once across all topics — none dropped,
    # none duplicated.
    assert sorted(placed) == ["a#0", "a#1", "b#0"]
    assert len(placed) == len(set(placed))


def test_forgotten_story_becomes_its_own_topic_labelled_with_its_title() -> None:
    stories = [_story("a#0", "Grouped"), _story("b#0", "Left out")]
    client = _fake_client(DraftTopic(label="Group", story_ids=["a#0"]))

    topics = cluster(stories, client=client)

    # The story the model left out lands in its own one-story topic, named after
    # the story itself.
    singletons = [t for t in topics if [s.id for s in t.stories] == ["b#0"]]
    assert len(singletons) == 1
    assert singletons[0].label == "Left out"


def test_hallucinated_ids_are_dropped_not_invented() -> None:
    stories = [_story("a#0")]
    # The model names a real id and one we never sent.
    client = _fake_client(DraftTopic(label="Topic", story_ids=["a#0", "ghost#9"]))

    topics = cluster(stories, client=client)

    placed = [s.id for t in topics for s in t.stories]
    # The invented id never makes it into a topic; only real input ids appear.
    assert placed == ["a#0"]


def test_story_named_in_two_topics_is_placed_only_once() -> None:
    stories = [_story("a#0"), _story("a#1")]
    # The model puts "a#0" in both topics; it must end up in only the first.
    client = _fake_client(
        DraftTopic(label="First", story_ids=["a#0", "a#1"]),
        DraftTopic(label="Second", story_ids=["a#0"]),
    )

    topics = cluster(stories, client=client)

    placed = [s.id for t in topics for s in t.stories]
    assert sorted(placed) == ["a#0", "a#1"]
    # The second topic ends up empty once "a#0" is already placed, so it is dropped.
    assert [t.label for t in topics] == ["First"]


def test_empty_input_yields_no_topics_without_calling_the_model() -> None:
    client = _fake_client(DraftTopic(label="ignored", story_ids=["x#0"]))

    topics = cluster([], client=client)

    assert topics == []
    # Nothing to group, so the model is never asked — no request, no cost.
    assert client.chat.completions.call_count == 0


def test_label_is_trimmed() -> None:
    stories = [_story("a#0")]
    client = _fake_client(DraftTopic(label="  Spacey label  ", story_ids=["a#0"]))

    [topic] = cluster(stories, client=client)

    assert topic.label == "Spacey label"


def test_prompt_carries_each_story_id_title_and_snippet() -> None:
    stories = [
        _story("a#0", "Chips bounce", "Intel rose 10% on Monday."),
        _story("b#0", "Bonds dip", "Treasuries fell on the news."),
    ]
    client = _fake_client(DraftTopic(label="t", story_ids=["a#0", "b#0"]))

    cluster(stories, client=client)

    messages = cast(list[dict[str, object]], client.chat.completions.messages)
    user_turns = [m for m in messages if m.get("role") == "user"]
    assert len(user_turns) == 1
    content = user_turns[0]["content"]
    assert isinstance(content, str)
    for story in stories:
        assert story.id in content
        assert story.title in content
    assert "Intel rose 10% on Monday." in content


def test_requests_the_clustering_schema() -> None:
    client = _fake_client(DraftTopic(label="t", story_ids=["a#0"]))

    cluster([_story("a#0")], client=client)

    assert client.chat.completions.response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "Clustering",
            "schema": Clustering.model_json_schema(),
        },
    }


def test_clustering_uses_raised_reasoning_effort() -> None:
    client = _fake_client(DraftTopic(label="t", story_ids=["a#0"]))

    cluster([_story("a#0")], client=client)

    # Grouping weighs every story against every other, so this call turns the
    # model's reasoning up from the helper's "low" default.
    assert client.chat.completions.reasoning_effort == "high"
