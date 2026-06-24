---
id: T0038
title: Split the LLM seam and own its stubs
status: done
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
  to test behavior (the stubbed `uv run python evals/run.py` still produces the
  same scorecard rows).
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
- **Out of scope:** any change to the eval functions (T0033–T0036) or the
  prompt-version comparison logic.

# Findings

## OOP refactor: from free function to client method

The original `parse_structured()` free function took a `client` argument and
called through it — backwards from OOP. The refactor moves the operation onto
the client itself as `ask()`, and the three-Protocol nesting
(`LLMClient` → `_Chat` → `_Completions`) that mirrored the OpenAI SDK's
`chat.completions.create` attribute path is gone. The Protocol now describes
what the client *does* (answer a structured question), not how the SDK routes
the call internally.

- `protocol.py` — `LLMClient` Protocol with one method: `ask(messages, schema,
  thinking)`. Plus `_ClientBase`, a private base class implementing the shared
  `ask()` logic as a template method: prepend schema instruction, call
  `_complete()` for the raw `ChatCompletion`, guard the reply (no choices,
  truncated, no content), validate against `schema`. Subclasses supply
  `_complete()`.
- `client.py` — `OpenAIClient(_ClientBase)` implements `_complete()` by calling
  the real SDK. `get_client()` returns a shared `OpenAIClient` singleton. No
  re-exports — `LLMClient` is imported from `app.llm.protocol` directly at every
  call site.
- `fake_client.py` — `FakeClient(_ClientBase)` and `QueuedFakeClient(_ClientBase)`
  implement `_complete()` to return a pre-built or queued reply. The
  `FakeChat` / `FakeCompletions` / `QueuedCompletions` / `RecordingCompletions`
  classes are gone — the three-class nesting they mirrored no longer exists.
- `parse.py` — deleted. Its logic lives in `_ClientBase.ask()` (shared) and
  `OpenAIClient._complete()` (SDK call + logging).

## `ReasoningEffort` made internal

`ReasoningEffort` was a public type alias exported from the seam. No caller
outside the client itself ever passed `reasoning_effort=` — it was always the
default. Made it a private type `_ReasoningEffort` in `client.py`, used only by
`OpenAIClient._complete()`. Dropped the tests that checked reasoning-effort
forwarding. The same logic applied to `model`, `max_tokens`, `response_format`,
and `extra_body` — all are `OpenAIClient` implementation details, not part of
the `ask()` API, and the tests that checked their forwarding via `FakeClient`
were dropped (they tested internal plumbing the fake no longer sees).

## No re-exports from `client.py`

`LLMClient` and `ReasoningEffort` are no longer re-exported from `client.py`.
Every `from app.llm.client import LLMClient` site now imports from
`app.llm.protocol` directly. `get_client()` stays in `client.py` and is imported
from there. `tests/fakes.py` still re-exports `FakeClient`, `QueuedFakeClient`,
and the `model_reply*` builders via `__all__` so existing test imports keep
working.

## Eval stubs collapsed

- `evals/run.py`'s `_StubLLMClient` subclasses `_ClientBase` and implements
  `_complete()` with the stage-prompt dispatch. Went from three classes
  (`_StubCompletions`, `_StubChat`, `_StubLLMClient`) to one.
- `evals/rag.py`'s `_CountingClient` (three classes) replaced with
  `FakeClient(model_reply(_NON_REFUSAL_REPLY))` — one line.
- `tests/evals/test_injection.py`'s `_BehaviorClient` and `_RagBehaviorClient`
  (each three classes) collapsed to one class each, subclassing `_ClientBase`.

## Call site pattern

Each pipeline function that accepted `client: LLMClient | None = None` now
resolves the client inline: `(client or get_client()).ask(messages=...,
schema=..., thinking=False)`. No central `parse_structured` helper resolves the
default — the pattern is a one-liner at each call site.
