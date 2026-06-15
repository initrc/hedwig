---
id: T0005
title: Move samples to backend
status: new
dependencies:
  - T0004
---

# Scope

- Move the `samples/` directory from the repo root to `backend/samples/`. It is consumed only by
  the backend (`LocalEmlSource`, the parser, the `dump` CLI, and their tests); no other part of the
  project reads it, so colocating it with its only consumer removes a cross-directory dependency and
  simplifies the relative-path math in the call sites.

# Acceptance

- All `.eml` files and `samples/README.md` live under `backend/samples/`; nothing references the old
  root-level `samples/`.
- `backend/app/ingest/dump.py` defaults to the new location and still writes one item per `.eml`.
- The committed tests still read from `samples/` at its new path and pass.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Use `git mv samples backend/samples` to preserve file history.
- Path call sites to update (the parser and CLI were added in T0004; the source + its test in T0002):
  - `backend/app/ingest/dump.py`: `DEFAULT_SAMPLES_DIR` is `Path(__file__).resolve().parents[3] / "samples"`
    (repo root). After the move it becomes `parents[2] / "samples"` (i.e. `backend/samples`).
  - `backend/tests/test_parser.py` and `backend/tests/test_local_eml_source.py`: `SAMPLES_DIR` is
    `Path(__file__).resolve().parents[2] / "samples"` (repo root); after the move it becomes
    `parents[1] / "samples"` (`backend/samples`).
- `LocalEmlSource` itself takes `samples_dir` as a required argument and hardcodes no path, so
  `backend/app/ingest/source.py` does not need to change.
- The address-scrubbing instructions in T0004 ("run from inside `samples/`") still apply; they are
  relative to the directory, so only the directory's location changes.
- Watch out: this edits path math in a test committed by T0002 (`test_local_eml_source.py`). Run the
  full suite after the move to confirm both that test and the T0004 parser tests stay green.
