"""Load the labeled eval fixtures into typed, validated models.

Two labeled sets underpin the eval suite:

- `topic_labels.json` — one `LabeledStory` per segmented story, with the
  hand-assigned expected topic. T0033 scores topic assignment against these.
- `golden_qa.json` — `GoldenQA` entries pairing a question with the source ids
  that should answer it (or `expect_refusal` for out-of-corpus probes). T0034
  and T0035 score retrieval and the refusal guardrail against these.

The loader reads each fixture through a Pydantic `TypeAdapter` so a malformed
fixture (a missing field, an empty label, a non-list top level) raises a
`ValidationError` instead of silently passing through.
"""

from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

# Directory holding the labeled fixtures, resolved relative to this module so
# the loader works regardless of the caller's working directory.
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class LabeledStory(BaseModel):
    """One segmented story with its hand-labeled expected topic.

    `source_item_id` is the parent `ParsedEmail.id` (the `.eml` filename for
    local samples); `story_id` is the `Story.id` (`{source_item_id}#{index}`,
    built in `app.pipeline.segment`). `title` and `text` carry enough of the
    story to reproduce the cluster input without re-running segmentation.
    `expected_topic` is a free-form short label chosen by hand — it does not
    need to match the LLM's wording, since T0033 scores topic assignment by
    story co-membership, not string match.
    """

    story_id: str
    source_item_id: str
    title: str
    text: str
    expected_topic: str = Field(min_length=1)


class GoldenQA(BaseModel):
    """One golden question and the source ids that should answer it.

    For in-corpus questions, `expected_source_ids` lists the `ParsedEmail.id`(s)
    whose `clean_text` contains the answer. For out-of-corpus questions
    (weather, recipes, car prices), leave `expected_source_ids` empty and set
    `expect_refusal: true` — the guardrail should refuse these. `topic_label`
    optionally scopes a question to one labeled topic for scoped retrieval.
    """

    question: str = Field(min_length=1)
    expected_source_ids: list[str] = Field(default_factory=list)
    topic_label: str | None = None
    expect_refusal: bool = False


_TOPIC_LABELS_ADAPTER: TypeAdapter[list[LabeledStory]] = TypeAdapter(list[LabeledStory])
_GOLDEN_QA_ADAPTER: TypeAdapter[list[GoldenQA]] = TypeAdapter(list[GoldenQA])


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Eval fixture not found: {path}")
    return path.read_text(encoding="utf-8")


def load_topic_labels(path: Path | None = None) -> list[LabeledStory]:
    """Load and validate the topic-labeling fixture.

    Defaults to `fixtures/topic_labels.json`. Raises `FileNotFoundError` if the
    file is missing, or `ValidationError` if any entry is malformed (e.g. an
    empty `expected_topic` or a missing `story_id`).
    """
    resolved = path or (FIXTURES_DIR / "topic_labels.json")
    return _TOPIC_LABELS_ADAPTER.validate_json(_read_text(resolved))


def load_golden_qa(path: Path | None = None) -> list[GoldenQA]:
    """Load and validate the golden Q&A fixture.

    Defaults to `fixtures/golden_qa.json`. Raises `FileNotFoundError` if the
    file is missing, or `ValidationError` if any entry is malformed (e.g. a
    missing `question`).
    """
    resolved = path or (FIXTURES_DIR / "golden_qa.json")
    return _GOLDEN_QA_ADAPTER.validate_json(_read_text(resolved))


__all__ = [
    "FIXTURES_DIR",
    "GoldenQA",
    "LabeledStory",
    "ValidationError",
    "load_golden_qa",
    "load_topic_labels",
]
