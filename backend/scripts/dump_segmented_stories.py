"""Dump segmented stories from the sample emails into a labeling skeleton.

One-off helper for T0032: runs the Day 1–2 pipeline (parse + segment) over the
real `.eml` samples and writes `topic_labels.skeleton.json`, which the human
fills in by hand. Each entry has `story_id`, `source_item_id`, `title`, and
`text` already populated; `expected_topic` is left empty for the human to label
(the loader rejects empty labels, so the skeleton is kept separate from
`topic_labels.json` until every label is filled in).

Not part of the automated suite — it calls the real DeepSeek segmenter. Run
once with `DEEPSEEK_API_KEY` in `.env`, from inside `backend/`:

    uv run python scripts/dump_segmented_stories.py

It also prints the `ParsedEmail.id -> subject` map, useful for writing the
golden Q&A entries in `backend/evals/fixtures/golden_qa.json`.
"""

import json
import sys
from pathlib import Path

# Running `uv run python scripts/foo.py` puts `backend/scripts/` on sys.path,
# not `backend/`, so `app` is not importable. `pyproject.toml`'s `pythonpath`
# only applies to pytest. Insert the project root so the imports resolve
# regardless of how the script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest.parser import parse  # noqa: E402
from app.ingest.source import LocalEmlSource  # noqa: E402
from app.llm.client import get_client  # noqa: E402
from app.pipeline.segment import segment  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SKELETON_PATH = (
    Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "topic_labels.skeleton.json"
)


def main() -> None:
    source = LocalEmlSource(SAMPLES_DIR)
    client = get_client()

    print(f"Reading samples from {SAMPLES_DIR}")
    entries: list[dict[str, str]] = []
    for raw in source.fetch():
        email = parse(raw)
        print(f"  [{email.id}] {email.subject}")
        stories = segment(email, client=client)
        for story in stories:
            entries.append(
                {
                    "story_id": story.id,
                    "source_item_id": story.source_item_id,
                    "title": story.title,
                    "text": story.text,
                    "expected_topic": "",
                }
            )
        print(f"    -> {len(stories)} story(ies)")

    SKELETON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKELETON_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(entries)} stories to {SKELETON_PATH}")
    print("Fill in 'expected_topic' for each, then merge into topic_labels.json.")


if __name__ == "__main__":
    main()
