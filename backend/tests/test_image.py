"""Tests for `app.pipeline.image`, the per-topic image-selection step.

These never reach the network or spend money. Each test that calls `select_image`
hands it a `FakeClient` (from `tests.fakes`) in place of the real Groq connection:
the fake remembers the request it was given and replies with a fixed answer. So we
control which index "the model returned" and check that `select_image` resolves
that index back to a real candidate, never invents a url, and treats null or an
out-of-range index as "no image". `gather_candidates` needs no client at all — it
just unions images the parser already attached to the source emails.
"""

from datetime import UTC, datetime
from typing import cast

from app.ingest.parser import CandidateImage, ParsedEmail
from app.pipeline.cluster import Topic
from app.pipeline.image import ImageChoice, gather_candidates, select_image
from app.pipeline.segment import Story
from tests.fakes import FakeClient, model_reply


def _fake_client(index: int | None) -> FakeClient:
    """A fake client whose reply picks this index (or null for no image)."""
    return FakeClient(model_reply(ImageChoice(index=index).model_dump_json()))


def _story(source_item_id: str, title: str = "A story") -> Story:
    """A minimal `Story` whose source email id is what image-gathering follows."""
    return Story(id=f"{source_item_id}#0", source_item_id=source_item_id, title=title, text="Body.")


def _image(
    url: str, alt: str = "", width: int | None = None, height: int | None = None
) -> CandidateImage:
    """A minimal candidate image."""
    return CandidateImage(url=url, alt=alt, width=width, height=height)


def _email(email_id: str, images: list[CandidateImage]) -> ParsedEmail:
    """A `ParsedEmail` carrying just the candidate images a test cares about."""
    return ParsedEmail(
        id=email_id,
        source="news@example.com",
        subject="Daily digest",
        received_at=datetime(2026, 6, 15, tzinfo=UTC),
        clean_text="Body text.",
        candidate_images=images,
        original_url=None,
    )


def _topic(*stories: Story, label: str = "Some topic") -> Topic:
    """A `Topic` over these stories."""
    return Topic(label=label, stories=list(stories))


def test_picks_a_content_image_over_a_logo() -> None:
    candidates = [
        _image("https://x/logo.png", alt="Acme logo", width=120, height=120),
        _image("https://x/chart.png", alt="Benchmark scores by model", width=650, height=366),
    ]
    # The model returns the chart's index; selection must return the chart itself.
    chosen = select_image(_topic(_story("a.eml")), candidates, client=_fake_client(1))

    assert chosen is candidates[1]


def test_returns_none_for_an_all_junk_pool() -> None:
    candidates = [
        _image("https://x/logo.png", alt="Acme logo", width=120, height=120),
        _image("https://x/ad.png", alt="Sponsored", width=600, height=200),
    ]
    # Nothing illustrates the story, so the model returns null.
    chosen = select_image(_topic(_story("a.eml")), candidates, client=_fake_client(None))

    assert chosen is None


def test_empty_pool_returns_none_without_calling_the_model() -> None:
    client = _fake_client(0)

    chosen = select_image(_topic(_story("a.eml")), [], client=client)

    assert chosen is None
    # No candidates to weigh, so the model is never asked — no request, no cost.
    assert client.chat.completions.call_count == 0


def test_chosen_image_is_always_one_of_the_candidates() -> None:
    candidates = [_image("https://x/0.png"), _image("https://x/1.png"), _image("https://x/2.png")]

    chosen = select_image(_topic(_story("a.eml")), candidates, client=_fake_client(2))

    # The returned object is the very same input object, not a copy or a new url.
    assert chosen is candidates[2]
    assert chosen in candidates


def test_out_of_range_index_becomes_no_image() -> None:
    candidates = [_image("https://x/0.png")]
    # The model names an index past the end of the list; it must not reach back
    # into real data, so the result is "no image".
    chosen = select_image(_topic(_story("a.eml")), candidates, client=_fake_client(5))

    assert chosen is None


def test_negative_index_becomes_no_image() -> None:
    candidates = [_image("https://x/0.png"), _image("https://x/1.png")]

    chosen = select_image(_topic(_story("a.eml")), candidates, client=_fake_client(-1))

    # A negative index would wrap around to a real list slot in plain Python; the
    # range check rejects it instead of picking the wrong image.
    assert chosen is None


def test_requests_the_image_choice_schema() -> None:
    client = _fake_client(0)

    select_image(_topic(_story("a.eml")), [_image("https://x/0.png")], client=client)

    assert client.chat.completions.response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "ImageChoice",
            "schema": ImageChoice.model_json_schema(),
        },
    }


def test_prompt_carries_the_topic_label_and_each_candidate() -> None:
    candidates = [
        _image("https://x/chart.png", alt="Benchmark scores", width=650, height=366),
        _image("https://x/plain.png"),
    ]
    client = _fake_client(0)

    select_image(_topic(_story("a.eml"), label="Model benchmarks"), candidates, client=client)

    messages = cast(list[dict[str, object]], client.chat.completions.messages)
    user_turns = [m for m in messages if m.get("role") == "user"]
    assert len(user_turns) == 1
    content = user_turns[0]["content"]
    assert isinstance(content, str)
    # The label and the first image's alt and size are all shown to the model.
    assert "Model benchmarks" in content
    assert "Benchmark scores" in content
    assert "650x366 px" in content
    # An image with no alt or size is still listed, marked as missing.
    assert "(no alt text)" in content
    assert "size unknown" in content


def test_gather_unions_images_across_a_topics_source_emails() -> None:
    emails_by_id = {
        "a.eml": _email("a.eml", [_image("https://x/a1.png"), _image("https://x/a2.png")]),
        "b.eml": _email("b.eml", [_image("https://x/b1.png")]),
    }
    topic = _topic(_story("a.eml"), _story("b.eml"))

    pool = gather_candidates(topic, emails_by_id)

    assert [img.url for img in pool] == ["https://x/a1.png", "https://x/a2.png", "https://x/b1.png"]


def test_gather_visits_each_source_email_only_once() -> None:
    emails_by_id = {"a.eml": _email("a.eml", [_image("https://x/a1.png")])}
    # Two stories from the same email must not pull that email's images twice.
    topic = _topic(_story("a.eml", "First"), _story("a.eml", "Second"))

    pool = gather_candidates(topic, emails_by_id)

    assert [img.url for img in pool] == ["https://x/a1.png"]


def test_gather_drops_the_same_url_seen_in_two_emails() -> None:
    shared = "https://x/shared.png"
    emails_by_id = {
        "a.eml": _email("a.eml", [_image(shared)]),
        "b.eml": _email("b.eml", [_image(shared), _image("https://x/b2.png")]),
    }
    topic = _topic(_story("a.eml"), _story("b.eml"))

    pool = gather_candidates(topic, emails_by_id)

    # The picture both emails reference appears once, not twice.
    assert [img.url for img in pool] == [shared, "https://x/b2.png"]


def test_gather_skips_a_story_whose_source_email_is_missing() -> None:
    emails_by_id = {"a.eml": _email("a.eml", [_image("https://x/a1.png")])}
    # "ghost.eml" is referenced by a story but absent from the map; skip it.
    topic = _topic(_story("a.eml"), _story("ghost.eml"))

    pool = gather_candidates(topic, emails_by_id)

    assert [img.url for img in pool] == ["https://x/a1.png"]
