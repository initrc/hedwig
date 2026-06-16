"""Tests for `app.pipeline.summarize`, the per-topic write-up step.

These never reach the network or spend money. Each test hands `summarize_topic` a
`FakeClient` (from `tests.fakes`) in place of the real Groq connection: the fake
remembers the request it was given and replies with a fixed answer. So we control
what "the model returned" and check that `summarize_topic` builds the right
prompt, asks for the `DraftSummary` shape, and — most of all — checks the model's
citations, keeping only those that trace back to a source newsletter that really
fed the topic.
"""

from typing import cast

from app.pipeline.cluster import Topic
from app.pipeline.segment import Story
from app.pipeline.summarize import (
    DraftSummary,
    TopicSummary,
    summarize_topic,
    summarize_topics,
)
from tests.fakes import FakeClient, model_reply


def _fake_client(draft: DraftSummary) -> FakeClient:
    """A fake client whose reply is exactly this draft summary."""
    return FakeClient(model_reply(draft.model_dump_json()))


def _story(story_id: str, source_item_id: str, title: str = "Title", text: str = "Body.") -> Story:
    """A minimal `Story` for a summarization test."""
    return Story(id=story_id, source_item_id=source_item_id, title=title, text=text)


def _topic(label: str, *stories: Story) -> Topic:
    """A `Topic` over the given stories."""
    return Topic(label=label, stories=list(stories))


def test_multi_source_topic_gets_a_summary_and_at_least_one_citation() -> None:
    topic = _topic(
        "Acme funding",
        _story("a#0", "alpha.eml", "Acme raises $50M"),
        _story("b#0", "beta.eml", "Acme round led by Foo Capital"),
    )
    client = _fake_client(
        DraftSummary(
            summary="Acme raised $50M in a round led by Foo Capital.",
            source_ids=["alpha.eml", "beta.eml"],
        )
    )

    result = summarize_topic(topic, client=client)

    assert isinstance(result, TopicSummary)
    assert result.label == "Acme funding"
    assert result.summary == "Acme raised $50M in a round led by Foo Capital."
    assert len(result.sources) >= 1
    assert {s.source_item_id for s in result.sources} == {"alpha.eml", "beta.eml"}


def test_every_citation_traces_back_to_a_source_in_the_topic() -> None:
    topic = _topic(
        "Chips",
        _story("a#0", "alpha.eml"),
        _story("a#1", "alpha.eml"),
        _story("b#0", "beta.eml"),
    )
    # The model cites two real sources and one it made up.
    client = _fake_client(
        DraftSummary(summary="Chip news.", source_ids=["alpha.eml", "ghost.eml", "beta.eml"])
    )

    result = summarize_topic(topic, client=client)

    valid = {story.source_item_id for story in topic.stories}
    # No citation points outside the topic's source newsletters, and the made-up
    # one never appears.
    assert all(s.source_item_id in valid for s in result.sources)
    assert "ghost.eml" not in {s.source_item_id for s in result.sources}


def test_duplicate_citations_are_kept_only_once_in_order() -> None:
    topic = _topic(
        "Pair",
        _story("a#0", "alpha.eml"),
        _story("b#0", "beta.eml"),
    )
    client = _fake_client(
        DraftSummary(summary="Two things.", source_ids=["beta.eml", "alpha.eml", "beta.eml"])
    )

    result = summarize_topic(topic, client=client)

    # Each real source cited once, in the order the model first named it.
    assert [s.source_item_id for s in result.sources] == ["beta.eml", "alpha.eml"]


def test_summary_is_trimmed() -> None:
    topic = _topic("Topic", _story("a#0", "alpha.eml"))
    client = _fake_client(DraftSummary(summary="  padded summary  ", source_ids=["alpha.eml"]))

    result = summarize_topic(topic, client=client)

    assert result.summary == "padded summary"


def test_prompt_carries_the_label_and_each_story_source_title_and_text() -> None:
    topic = _topic(
        "Chips bounce",
        _story("a#0", "alpha.eml", "Intel up", "Intel rose 10% on Monday."),
        _story("b#0", "beta.eml", "AMD up", "AMD followed."),
    )
    client = _fake_client(DraftSummary(summary="s", source_ids=["alpha.eml"]))

    summarize_topic(topic, client=client)

    # The Groq message type is a union of TypedDicts, so inspect the recorded
    # messages as the plain dicts they are at runtime.
    messages = cast(list[dict[str, object]], client.chat.completions.messages)
    user_turns = [m for m in messages if m.get("role") == "user"]
    assert len(user_turns) == 1
    content = user_turns[0]["content"]
    assert isinstance(content, str)
    assert "Chips bounce" in content
    for story in topic.stories:
        # We cite by the source id, so it must reach the model.
        assert story.source_item_id in content
        assert story.title in content
    assert "Intel rose 10% on Monday." in content


def test_requests_the_draft_summary_schema() -> None:
    topic = _topic("Topic", _story("a#0", "alpha.eml"))
    client = _fake_client(DraftSummary(summary="s", source_ids=["alpha.eml"]))

    summarize_topic(topic, client=client)

    assert client.chat.completions.response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "DraftSummary",
            "schema": DraftSummary.model_json_schema(),
        },
    }


def test_summarize_topics_maps_over_a_list_in_order() -> None:
    topics = [
        _topic("First", _story("a#0", "alpha.eml")),
        _topic("Second", _story("b#0", "beta.eml")),
    ]
    client = _fake_client(DraftSummary(summary="s", source_ids=["alpha.eml"]))

    results = summarize_topics(topics, client=client)

    assert [r.label for r in results] == ["First", "Second"]
    assert client.chat.completions.call_count == 2
