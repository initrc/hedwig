---
id: T0038
title: Split the LLM seam and own its stubs
status: new
dependencies:
  - T0037
---

# Scope

- Split `backend/app/llm/client.py` along its three current concerns into separate
  files so a reader can find each by name:
  - `backend/app/llm/protocol.py` — the seam: the `LLMClient` Protocol and its
    helper Protocols (`_Chat`, `_Completions`), plus the `ReasoningEffort` literal.
  - `backend/app/llm/client.py` — the real DeepSeek implementation: `get_client()`,
    `DEFAULT_MODEL`, `DEEPSEEK_BASE_URL`, `DEFAULT_REASONING_EFFORT`,
    `DEFAULT_MAX_TOKENS`.
  - `backend/app/llm/parse.py` — the call helper: `parse_structured()`.
- Move the **pure client stubs** out of `backend/tests/fakes.py` into
  `backend/app/llm/fake_client.py`, owned by the LLM seam: `FakeClient`,
  `FakeChat`, `FakeCompletions`, `QueuedFakeClient`, `QueuedCompletions`, and the
  `model_reply` / `model_reply_without_choices` / `model_reply_truncated` reply
  builders. Keep `backend/tests/fakes.py` re-exporting them so existing tests
  keep importing from `tests.fakes` without churn.
- Rewrite the eval runner's dispatching stub (`_StubLLMClient` in
  `backend/evals/run.py`) on top of the now-shared pure-stub base so the
  three-class `client.chat.completions.create` plumbing is not reimplemented.
  The runner keeps the eval-specific dispatch table (which stage prompt gets
  which stub reply) — that stays in `evals/`, because it is eval behavior, not
  seam infrastructure.

# Acceptance

- `backend/app/llm/` is organized as `protocol.py`, `client.py`, `parse.py`, and
  `fake_client.py`. A reader looking for "what shape does a fake need to
  implement" opens `protocol.py`; "how do we build the real DeepSeek connection"
  opens `client.py`; "how do I call the model and get a typed object" opens
  `parse.py`; "what are the canonical stubs" opens `fake_client.py`.
- `LLMClient`, `_Chat`, `_Completions`, and `ReasoningEffort` are importable from
  `app.llm.protocol`. Existing imports of these names from `app.llm.client` keep
  working (re-export, no test churn) OR every import site is updated — pick one
  approach and apply it consistently; record the choice in the task findings.
- The pure stubs (`FakeClient`, `FakeChat`, `FakeCompletions`, `QueuedFakeClient`,
  `QueuedCompletions`, `model_reply*`) live in `app/llm/fake_client.py` and are
  re-exported from `tests/fakes.py` so existing test imports are unchanged.
- `evals/run.py`'s `_StubLLMClient` composes or subclasses the pure-stub base
  rather than redeclaring `_StubChat` / `_StubCompletions`. The three-class
  nesting plumbing lives once (in `app/llm/fake_client.py`), not twice. The
  runner still owns the dispatch-by-prompt behavior — that part is not moved.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass with no change
  to test behavior (the stubbed `python evals/run.py` still produces the same
  scorecard rows).
- No behavior change: the split is a structural refactor. The one documented
  exception is that `_StubLLMClient` now shares plumbing with the pure stubs,
  which is the point of the task.

# Implementation Notes

- The architectural reasoning is in the T0037 review thread and the "Split the
  LLM seam and own its stubs" discussion. The short version: `app/llm/client.py`
  today conflates three concerns (the interface, the implementation, and the
  call helper), and the pure client stubs are scattered across `tests/fakes.py`
  and `evals/run.py` — so a change to the seam's shape silently breaks stubs
  owned by other teams (the drift class of bug T0037 just fixed by switching to
  identity-based dispatch). This task owns the cleanup properly.
- **Split the seam, don't move behavior.** `parse_structured`'s logic (the
  schema-instruction prepend, the `extra_body` thinking toggle, the
  `finish_reason == "length"` guard, the timed logging) stays in `parse.py`
  unchanged. Moving the file is the change; rewriting the helper is not.
- **Keep the dependency direction correct.** `parse.py` imports from
  `protocol.py`. `client.py` imports from `protocol.py`. `fake_client.py`
  imports from `protocol.py` (so the stubs satisfy the contract the seam
  declares). Nothing in `app/llm/` imports from `app/pipeline/` or `evals/` —
  the seam does not know about the stages that use it. The dispatching stub in
  `evals/run.py` imports stage prompts from `app/pipeline/` and `app/rag/`, and
  that is the right direction: evals depends on the pipeline, not the reverse.
- **Two kinds of stub, two homes.** A *pure client stub* (records calls, returns
  a fixed or queued reply, knows nothing about stages) is seam infrastructure
  → `app/llm/fake_client.py`, implementor-owned. A *behavior stub* (returns
  contextually correct replies that vary by stage prompt) is eval-specific
  knowledge → stays in `evals/`. Conflating them is what would couple the LLM
  seam to the pipeline's stage prompts; the split keeps the dependency arrows
  pointing the right way.
- **`_StubLLMClient` composition.** `tests/fakes.py`'s `QueuedFakeClient`
  already returns a *sequence* of replies keyed by call order; the runner's
  dispatching stub is "QueuedFakeClient, but the selection key is *which prompt
  is in flight* instead of *call number*." Factor the shared plumbing (the
  `chat` / `completions` nesting, `call_count`, the create-signature) into the
  pure-stub base and let the runner supply only the reply-selection key. Aim for
  the runner's stub to be one class (or one class + one small helper), not three.
- **Re-export vs. update imports.** The low-churn path is to re-export from
  `app/llm/client.py` and `tests/fakes.py` so no call site changes. The
  cleaner-but-more-work path is to update every import site to point at the new
  home and drop the re-exports. Either is acceptable; pick one and apply it
  consistently. If you re-export, leave a one-line comment in the new file
  pointing at the legacy re-export so future readers know the old path still
  works on purpose.
- **Consider revisiting the `_Chat` / `_Completions` split while the seam is
  open.** Those two private Protocols exist only so mypy can check a
  doubly-nested attribute access (`client.chat.completions.create`). Since
  `parse_structured` always calls exactly that path, they describe a shape that
  cannot vary. A single `LLMClient` Protocol with an inline `chat` return type
  might be enough. This is optional and a judgment call — if the three-Protocol
  nesting reads clearer to you after the split, keep it; if a collapsed single
  Protocol reads cleaner, collapse it. Record the choice and the reason in the
  task findings either way.
- **Out of scope:** any change to `parse_structured`'s behavior, the real
  DeepSeek client, the eval functions (T0033–T0036), or the prompt-version
  comparison logic. This task is the seam reorganization + stub consolidation,
  nothing more.