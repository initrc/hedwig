---
id: T0002
title: Define EmailSource interface and LocalEmlSource
status: done
dependencies:
  - T0001
---

# Scope

- Define an `EmailSource` abstraction that yields raw email messages, decoupled from where they come from.
- Implement `LocalEmlSource` that reads `.eml` files from `samples/` and yields them via the interface.
- The interface should expose just enough surface for the parser (T0004) to consume — do not bake in IMAP-specific concerns.

# Acceptance

- `EmailSource` is defined as a Protocol or ABC in `backend/hedwig/ingest/source.py` (or equivalent).
- `LocalEmlSource(samples_dir: Path)` iterates `samples/*.eml` and yields parsed `email.message.Message` objects (or a thin wrapper — see Implementation Notes).
- A unit test reads the committed `samples/*.eml` via `LocalEmlSource` and confirms messages are returned with non-empty `Subject` headers.
- `uv run pytest` passes; `uv run ruff check` passes; `uv run mypy` passes.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 1 step 2 (lines 87–91) — `EmailSource` interface with `LocalEmlSource` and `ImapSource`.
- Added `mypy` (strict) as the project type-checker during this task: declared in the `dev` dependency
  group with a `[tool.mypy]` config in `backend/pyproject.toml` targeting `app` and `tests`. This was
  not in the original scope but establishes a typed baseline for later tasks; `uv run mypy` is now part
  of the gate. Existing test functions were annotated `-> None` to satisfy strict mode.
- Use Python's stdlib `email` + `email.parser.BytesParser` to read `.eml` files. No third-party email lib needed.
- Suggested interface shape:
  ```python
  class EmailSource(Protocol):
      def fetch(self) -> Iterable[RawEmail]: ...
  ```
  where `RawEmail` is a small dataclass wrapping `email.message.Message` plus a stable `source_id` (e.g., filename for local, IMAP UID for remote). This avoids leaking `email.message.Message` everywhere and gives T0004's parser a stable id to use.
- Samples live at `samples/` in the repo root and are committed (scrubbed of personal email addresses — see T0004 for the scrub command). Tests can rely on `samples/` being present.
- Do NOT implement `ImapSource` here — that's T0003. Keep this task focused so the local path can land first.
- The parser (T0004) depends only on this task, not on T0003 — keep the interface deliberately minimal so both implementations satisfy it.
