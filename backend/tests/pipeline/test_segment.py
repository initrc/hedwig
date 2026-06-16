"""Tests for `app.pipeline.segment`, the per-story segmentation step.

These never reach the network or spend money. Each test hands `segment` a
`FakeClient` (from `tests.fakes`) in place of the real Groq connection: the fake
remembers the request it was given and replies with a fixed answer. So we control
what "the model returned" and check that `segment` builds the right prompt, asks
for the `Segmentation` shape, and turns the reply into `Story` objects with stable,
traceable ids.
"""

from pathlib import Path
from typing import cast

from app.ingest.parser import parse
from app.ingest.source import LocalEmlSource
from app.pipeline.segment import (
    DraftStory,
    Segmentation,
    Story,
    segment,
    segment_items,
)
from tests.fakes import FakeClient, _parsed_email, model_reply

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def _fake_client(*drafts: DraftStory) -> FakeClient:
    """A fake client whose reply is exactly these stories."""
    return FakeClient(model_reply(Segmentation(stories=list(drafts)).model_dump_json()))


def test_single_story_item_yields_one_story() -> None:
    client = _fake_client(DraftStory(title="Only story", text="It happened."))

    stories = segment(
        _parsed_email(clean_text="One thing happened today."), client=client
    )

    assert stories == [
        Story(
            id="news.eml#0",
            source_item_id="news.eml",
            title="Only story",
            text="It happened.",
        )
    ]
    assert client.chat.completions.call_count == 1


def test_multi_story_item_yields_several_stories() -> None:
    client = _fake_client(
        DraftStory(title="Story one", text="First."),
        DraftStory(title="Story two", text="Second."),
        DraftStory(title="Story three", text="Third."),
    )

    stories = segment(
        _parsed_email(item_id="digest.eml", clean_text="Three things happened."),
        client=client,
    )

    assert [s.title for s in stories] == ["Story one", "Story two", "Story three"]
    # The ids number the stories in order and trace back to the parent email.
    assert [s.id for s in stories] == ["digest.eml#0", "digest.eml#1", "digest.eml#2"]


def test_every_story_references_the_parent_item() -> None:
    parent = _parsed_email(item_id="parent.eml", clean_text="Lots of news.")
    client = _fake_client(
        DraftStory(title="A", text="a"),
        DraftStory(title="B", text="b"),
    )

    stories = segment(parent, client=client)

    assert stories, "expected at least one story"
    for story in stories:
        assert story.source_item_id == parent.id


def test_empty_clean_text_yields_no_stories_without_calling_the_model() -> None:
    client = _fake_client(DraftStory(title="ignored", text="ignored"))

    stories = segment(_parsed_email(clean_text=""), client=client)

    assert stories == []
    # Nothing to split, so the model is never asked — no request, no cost.
    assert client.chat.completions.call_count == 0


def test_whitespace_only_clean_text_yields_no_stories() -> None:
    client = _fake_client(DraftStory(title="ignored", text="ignored"))

    stories = segment(_parsed_email(clean_text="   \n  \t "), client=client)

    assert stories == []
    assert client.chat.completions.call_count == 0


def test_titles_and_text_are_trimmed() -> None:
    client = _fake_client(
        DraftStory(title="  Spacey title  ", text="\n  padded body  \n")
    )

    [story] = segment(_parsed_email(), client=client)

    assert story.title == "Spacey title"
    assert story.text == "padded body"


def test_prompt_carries_the_subject_and_body() -> None:
    client = _fake_client(DraftStory(title="t", text="x"))
    item = _parsed_email(
        subject="Chips bounce", clean_text="Intel rose 10% on Monday."
    )

    segment(item, client=client)

    # The Groq message type is a union of TypedDicts, so inspect the recorded
    # messages as the plain dicts they are at runtime: the user turn must carry both
    # the subject and the body so the model can split them.
    messages = cast(list[dict[str, object]], client.chat.completions.messages)
    user_turns = [m for m in messages if m.get("role") == "user"]
    assert len(user_turns) == 1
    content = user_turns[0]["content"]
    assert isinstance(content, str)
    assert "Chips bounce" in content
    assert "Intel rose 10% on Monday." in content


def test_requests_the_segmentation_schema() -> None:
    client = _fake_client(DraftStory(title="t", text="x"))

    segment(_parsed_email(), client=client)

    assert client.chat.completions.response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "Segmentation",
            "schema": Segmentation.model_json_schema(),
        },
    }


def test_segment_items_flattens_stories_across_emails() -> None:
    # Both emails get the same two-story reply from the fake, but each story's id
    # is built from its own parent, so the flat list stays traceable.
    client = _fake_client(
        DraftStory(title="A", text="a"),
        DraftStory(title="B", text="b"),
    )
    items = [
        _parsed_email(item_id="one.eml"),
        _parsed_email(item_id="two.eml"),
    ]

    stories = segment_items(items, client=client)

    assert [s.id for s in stories] == [
        "one.eml#0",
        "one.eml#1",
        "two.eml#0",
        "two.eml#1",
    ]
    assert {s.source_item_id for s in stories} == {"one.eml", "two.eml"}
    assert client.chat.completions.call_count == 2


def test_over_a_real_sample_every_story_id_is_valid() -> None:
    # Use a real parsed newsletter so the `ParsedEmail` is genuine, but still stub
    # the model: this proves the wiring end to end without a real API call. Every
    # story must trace back to the one email it came from.
    raw = next(iter(LocalEmlSource(SAMPLES_DIR).fetch()))
    item = parse(raw)
    client = _fake_client(
        DraftStory(title="First", text="first story"),
        DraftStory(title="Second", text="second story"),
    )

    stories = segment(item, client=client)

    assert [s.id for s in stories] == [f"{item.id}#0", f"{item.id}#1"]
    for story in stories:
        assert story.source_item_id == item.id
