"""CLI: parse the local `.eml` samples and dump normalized items to JSON.

    uv run python -m app.ingest.dump [--samples-dir DIR] [--output PATH]

Writes one JSON object per `.eml` file (default `out/items.json`) so the Day 2
steps have a stable, offline input to work against.
"""

import argparse
import json
from pathlib import Path

from app.ingest.parser import Item, parse
from app.ingest.source import LocalEmlSource

# parser.py lives at backend/app/ingest/dump.py; the repo root is four levels up,
# and the committed samples sit beside the backend at <repo>/samples.
DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"
DEFAULT_OUTPUT = Path("out/items.json")


def dump_items(samples_dir: Path, output: Path) -> list[Item]:
    """Parse every sample under `samples_dir` and write the items to `output`."""
    items = [parse(raw) for raw in LocalEmlSource(samples_dir).fetch()]
    payload = [item.model_dump(mode="json") for item in items]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="directory of .eml files to parse (default: <repo>/samples)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON file to write (default: out/items.json)",
    )
    args = parser.parse_args()
    items = dump_items(args.samples_dir, args.output)
    print(f"Wrote {len(items)} item(s) to {args.output}")


if __name__ == "__main__":
    main()
