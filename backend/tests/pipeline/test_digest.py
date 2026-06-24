"""Tests for `app.pipeline.digest`, the pipeline-composition step.

These never reach the network or spend money. Each test hands `run_pipeline` a
`QueuedFakeClient` (from `tests.fakes`) in place of the real DeepSeek connection, so
the pipeline runs through all four stages with controlled LLM replies — no stage
is patched or skipped. The assertions cover wiring and assembly, not prompt
behavior; the per-stage prompt behavior is already covered by each stage's own
tests.
"""

from datetime import UTC, date, datetime

import pytest

from app.llm.fake_client import FakeClient, QueuedFakeClient, model_reply
from app.pipeline.cluster import Clustering, DraftTopic
from app.pipeline.digest import _SELECT_TOPIC_IMAGES, Digest, run_pipeline
from app.pipeline.image import ImageChoice
from app.pipeline.segment import DraftStory, Segmentation
from app.pipeline.summarize import DraftSummary
from tests.fakes import make_image, make_parsed_email


def _segment_reply(*titles: str) -> Segmentation:
    """A segmentation reply with one story per title."""
    return Segmentation(stories=[DraftStory(title=t, text=f"{t} text.") for t in titles])


def _cluster_reply(*topics: tuple[str, list[str]]) -> Clustering:
    """A clustering reply grouping story ids into labelled topics."""
    return Clustering(
        topics=[DraftTopic(label=label, story_ids=ids) for label, ids in topics]
    )


def _summary_reply(summary: str, source_ids: list[str]) -> DraftSummary:
    """A summarization reply with the given text and source citations."""
    return DraftSummary(summary=summary, source_ids=source_ids)


def _image_reply(index: int | None) -> ImageChoice:
    """An image-selection reply picking the candidate at `index`, or none."""
    return ImageChoice(index=index)


# ---------------------------------------------------------------------------
# run_pipeline composition
# ---------------------------------------------------------------------------


def test_run_pipeline_composes_all_stages_and_round_trips() -> None:
    items = [
        make_parsed_email(
            item_id="alpha.eml",
            clean_text="Alpha news.",
        ),
        make_parsed_email(
            item_id="beta.eml",
            clean_text="Beta news.",
        ),
    ]

    # The pipeline makes 5 LLM calls in this order:
    #   1–2. segment (one per email)
    #   3.   cluster
    #   4–5. summarize_topic (one per topic)
    # Image selection is currently disabled by `_SELECT_TOPIC_IMAGES`.
    client = QueuedFakeClient(
        [
            # segment(alpha.eml)
            model_reply(_segment_reply("Alpha story").model_dump_json()),
            # segment(beta.eml)
            model_reply(_segment_reply("Beta story").model_dump_json()),
            # cluster → two topics
            model_reply(
                _cluster_reply(
                    ("Chips", ["alpha.eml#0"]),
                    ("Bonds", ["beta.eml#0"]),
                ).model_dump_json()
            ),
            # summarize_topic("Chips")
            model_reply(_summary_reply("Chip summary.", ["alpha.eml"]).model_dump_json()),
            # summarize_topic("Bonds")
            model_reply(_summary_reply("Bond summary.", ["beta.eml"]).model_dump_json()),
        ]
    )

    digest = run_pipeline(items, client=client)

    assert client.call_count == 5

    assert len(digest.topics) == 2
    assert digest.topics[0].label == "Chips"
    assert digest.topics[0].summary == "Chip summary."
    assert digest.topics[0].image is None
    assert digest.topics[1].label == "Bonds"
    assert digest.topics[1].summary == "Bond summary."
    assert digest.topics[1].image is None

    # The assembled object survives a JSON round-trip.
    reloaded = Digest.model_validate(digest.model_dump(mode="json"))
    assert reloaded == digest


def test_image_selection_is_skipped_by_default() -> None:
    assert _SELECT_TOPIC_IMAGES is False


def test_image_selection_runs_when_flag_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the feature flag is on, the pipeline still calls `select_image`."""
    image_a = make_image("https://x/a.png")

    items = [
        make_parsed_email(
            item_id="alpha.eml",
            clean_text="Alpha news.",
            candidate_images=[image_a],
        ),
    ]

    monkeypatch.setattr(
        "app.pipeline.digest._SELECT_TOPIC_IMAGES", True
    )

    client = QueuedFakeClient(
        [
            model_reply(_segment_reply("Alpha story").model_dump_json()),
            model_reply(_cluster_reply(("Chips", ["alpha.eml#0"])).model_dump_json()),
            model_reply(_summary_reply("Chip summary.", ["alpha.eml"]).model_dump_json()),
            model_reply(_image_reply(0).model_dump_json()),
        ]
    )

    digest = run_pipeline(items, client=client)

    assert client.call_count == 4
    assert digest.topics[0].image is image_a


def test_topic_sources_resolve_to_the_input_parsed_emails() -> None:
    items = [
        make_parsed_email(
            item_id="alpha.eml",
            source="alpha@news.com",
            subject="Alpha News",
            clean_text="Alpha text.",
        ),
        make_parsed_email(
            item_id="beta.eml",
            source="beta@news.com",
            subject="Beta News",
            clean_text="Beta text.",
        ),
    ]

    client = QueuedFakeClient(
        [
            model_reply(_segment_reply("Story 1").model_dump_json()),
            model_reply(_segment_reply("Story 2").model_dump_json()),
            model_reply(
                _cluster_reply(
                    ("Pair", ["alpha.eml#0", "beta.eml#0"]),
                ).model_dump_json()
            ),
            model_reply(
                _summary_reply("Two things.", ["alpha.eml", "beta.eml"]).model_dump_json()
            ),
        ]
    )

    digest = run_pipeline(items, client=client)

    [digest_topic] = digest.topics
    assert digest_topic.image is None
    assert len(digest_topic.sources) == 2

    alpha_source = next(s for s in digest_topic.sources if s.id == "alpha.eml")
    assert alpha_source.source == "alpha@news.com"
    assert alpha_source.subject == "Alpha News"
    assert alpha_source.clean_text == "Alpha text."
    assert alpha_source.original_url == "https://example.com/view/1"

    beta_source = next(s for s in digest_topic.sources if s.id == "beta.eml")
    assert beta_source.source == "beta@news.com"
    assert beta_source.subject == "Beta News"
    assert beta_source.clean_text == "Beta text."


def test_fallback_when_original_url_is_none_is_preserved() -> None:
    items = [
        make_parsed_email(
            item_id="alpha.eml",
            original_url=None,
            clean_text="Fallback text.",
        )
    ]

    client = QueuedFakeClient(
        [
            model_reply(_segment_reply("Solo").model_dump_json()),
            model_reply(_cluster_reply(("Solo", ["alpha.eml#0"])).model_dump_json()),
            model_reply(_summary_reply("One thing.", ["alpha.eml"]).model_dump_json()),
        ]
    )

    digest = run_pipeline(items, client=client)

    [source] = digest.topics[0].sources
    assert source.original_url is None
    assert source.clean_text == "Fallback text."


def test_date_defaults_to_today() -> None:
    digest = run_pipeline([], client=FakeClient(model_reply("{}")))

    assert digest.date == datetime.now(UTC).date()
    assert digest.topics == []


def test_date_override_is_honoured() -> None:
    digest = run_pipeline([], date=date(2026, 1, 15), client=FakeClient(model_reply("{}")))

    assert digest.date == date(2026, 1, 15)
    assert digest.topics == []


def test_empty_input_yields_empty_digest() -> None:
    digest = run_pipeline([], client=FakeClient(model_reply("{}")))

    assert digest.topics == []
