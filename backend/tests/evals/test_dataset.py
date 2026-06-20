"""Tests for the eval fixture loader (`app.evals.dataset`).

No real API calls: the loader is pure validation. We round-trip a good fixture
and assert the loader raises on a bad one. The real fixtures under
`backend/evals/fixtures/` are also loaded to make sure they validate.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.dataset import (
    GoldenQA,
    LabeledStory,
    load_golden_qa,
    load_topic_labels,
)

GOOD_TOPIC_LABELS: list[dict[str, object]] = [
    {
        "story_id": "news.eml#0",
        "source_item_id": "news.eml",
        "title": "Fed cuts rates",
        "text": "The Fed cut rates by 25 basis points.",
        "expected_topic": "monetary policy",
    },
    {
        "story_id": "news.eml#1",
        "source_item_id": "news.eml",
        "title": "New GPU launch",
        "text": "Vendor X launched a new GPU.",
        "expected_topic": "hardware",
    },
]

GOOD_GOLDEN_QA: list[dict[str, object]] = [
    {
        "question": "What did the Fed do?",
        "expected_source_ids": ["news.eml"],
        "topic_label": None,
        "expect_refusal": False,
    },
    {
        "question": "Which models launched?",
        "expected_source_ids": ["a.eml", "b.eml"],
        "topic_label": "AI launches",
        "expect_refusal": False,
    },
    {
        "question": "What's the weather?",
        "expected_source_ids": [],
        "topic_label": None,
        "expect_refusal": True,
    },
]


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return path


# -- topic_labels loader ----------------------------------------------------


def test_load_topic_labels_round_trips_good_fixture(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "topic_labels.json", GOOD_TOPIC_LABELS)
    labels = load_topic_labels(fixture)
    assert len(labels) == 2
    assert all(isinstance(item, LabeledStory) for item in labels)
    assert labels[0].expected_topic == "monetary policy"
    assert labels[1].story_id == "news.eml#1"


def test_load_topic_labels_rejects_empty_expected_topic(tmp_path: Path) -> None:
    bad_entry: dict[str, object] = {**GOOD_TOPIC_LABELS[0], "expected_topic": ""}
    with pytest.raises(ValidationError):
        load_topic_labels(_write(tmp_path / "bad.json", [bad_entry]))


def test_load_topic_labels_rejects_missing_story_id(tmp_path: Path) -> None:
    bad_entry: dict[str, object] = {
        k: v for k, v in GOOD_TOPIC_LABELS[0].items() if k != "story_id"
    }
    with pytest.raises(ValidationError):
        load_topic_labels(_write(tmp_path / "bad.json", [bad_entry]))


def test_load_topic_labels_rejects_non_list_fixture(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "bad.json", {"not": "a list"})
    with pytest.raises(ValidationError):
        load_topic_labels(fixture)


def test_load_topic_labels_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_topic_labels(tmp_path / "does_not_exist.json")


# -- golden_qa loader -------------------------------------------------------


def test_load_golden_qa_round_trips_good_fixture(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "golden_qa.json", GOOD_GOLDEN_QA)
    qa = load_golden_qa(fixture)
    assert len(qa) == 3
    assert all(isinstance(item, GoldenQA) for item in qa)
    assert qa[2].expect_refusal is True
    assert qa[2].expected_source_ids == []
    assert qa[1].topic_label == "AI launches"


def test_load_golden_qa_rejects_missing_question(tmp_path: Path) -> None:
    bad_entry: dict[str, object] = {
        k: v for k, v in GOOD_GOLDEN_QA[0].items() if k != "question"
    }
    with pytest.raises(ValidationError):
        load_golden_qa(_write(tmp_path / "bad.json", [bad_entry]))


def test_load_golden_qa_rejects_empty_question(tmp_path: Path) -> None:
    bad_entry: dict[str, object] = {**GOOD_GOLDEN_QA[0], "question": ""}
    with pytest.raises(ValidationError):
        load_golden_qa(_write(tmp_path / "bad.json", [bad_entry]))


def test_load_golden_qa_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_golden_qa(tmp_path / "does_not_exist.json")


# -- real fixtures validate -------------------------------------------------


def test_real_topic_labels_fixture_validates() -> None:
    """The shipped `topic_labels.json` must load (empty until the human labels)."""
    labels = load_topic_labels()
    assert isinstance(labels, list)
    assert all(isinstance(item, LabeledStory) for item in labels)


def test_real_golden_qa_fixture_validates() -> None:
    """The shipped `golden_qa.json` must load and every entry must be a `GoldenQA`."""
    qa = load_golden_qa()
    assert isinstance(qa, list)
    assert all(isinstance(item, GoldenQA) for item in qa)
    assert len(qa) >= 1
