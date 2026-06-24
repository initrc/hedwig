---
id: T0039
title: Fix live-mode RAG-injection store wiring in the eval runner
status: done
dependencies: []
---

# Scope

- The live eval scorecard's `rag_injection` row is meaningless today: in live
  mode (`evals/run.py --live`) `_build_evals` wires `rag_injection_store = store`
  — the real on-disk Chroma archive — which contains *no* chunks from the
  injection fixtures (`inj-rag-override.eml`, `inj-rag-exfil-url.eml`). The
  `eval_rag_injection` probe's contract (documented in its own module
  docstring) is that "the caller seeds `vector_store` with a chunk whose text
  carries the injection" so retrieval clears the guardrail and `ask()` reaches
  the LLM call where the injected text would take effect. In live mode that
  seed never happens, retrieval finds unrelated real chunks (or nothing), the
  guardrail behaves "wrong" from the probe's narrow perspective, and both rows
  come back `fail` with `guardrail misbehaved` — measuring nothing about the
  model's injection robustness.
- Fix the live wiring so the RAG-injection probe tests the real model against
  the real embeddings *while seeded with the injection chunks*: embed each
  injection-question chunk with the real `_live_embed()`, insert those real
  embeddings into an isolated store (a seeded `StubStore` is fine; a throwaway
  Chroma collection is also fine), have `eval_rag_injection` retrieve from that
  seeded store, and let `ask()` make its real LLM call. Retrieval is genuinely
  real (real embedded question vs. real embedded chunk); the only non-live
  piece is the store's contents, which is the point.

# Acceptance

- `uv run python evals/run.py --live` produces a `rag_injection` row whose
  pass/fail reflects whether the real DeepSeek answered in a way that ignored the
  injected chunk text — not a harness artifact. Specifically: retrieval must
  clear the 0.35 guardrail on the injected chunks (cosine ≥ 0.35 between the
  real question embedding and the real chunk-text embedding), and `ask()` must
  reach the real LLM call. The row's `detail` should show `confident=True` and
  `sources=N` (with N ≥ 1) for at least the in-corpus injection questions, so
  the only thing being scored is whether the model followed the injection.
- The stubbed path is unchanged: it still uses `_injection_chunk_store()` with
  the stub embedding and the stub LLM, and its scorecard rows are identical.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass. Existing
  runner tests (including `test_run_all_stubbed_never_constructs_a_real_client`)
  still pass — the live-only seeding must not leak into the stubbed path or
  construct a real client/store/embed when `live=False`.
- Re-run `--live` and update the reference baseline at
  `backend/evals/baselines/<date>-live.md` with the corrected `rag_injection`
  row so the repo keeps an honest snapshot.

# Implementation Notes

- The buggy line is in `backend/evals/run.py`, `_build_evals`: the
  `rag_injection_store = injection_store` (live branch) / `= store` assignment
  that was reconciled when fixing the basedpyright "possibly unbound" warning.
  The clean shape is: keep `injection_store` bound on both modes, but in live
  mode build it from a **seeded** store (`StubStore` or a throwaway Chroma
  collection) populated with **real** embeddings of the injection chunks, NOT
  the production archive.
- `eval_rag_injection` in `backend/evals/injection.py` documents the contract
  in its module docstring ("the caller seeds `vector_store`...") — the live
  runner has been violating it. The fix is to honor that contract in live mode.
- Reuse `_injection_chunk_store()` from `evals/run.py` as the *shape* of the
  seeded store, but swap the stub embedding for `_live_embed()`. The seeded
  store currently writes a fixed `_MATCH_VECTOR = [1.0, 0.0, 0.0]`; in live
  mode that must instead be `_live_embed()([q.chunk_text])[0]` per question, so
  the cosine similarity between the real question embedding and the real chunk
  embedding is what clears (or fails) the guardrail. Reference the existing
  stub-only path's `_chunk_header` / `_injection_chunk_store` helpers in run.py
  to avoid duplicating the `IndexChunk` metadata construction.
- This is a runner-wiring defect introduced during T0037's live/stubbed split
  and preserved through the basedpyright fix; it does not reflect a problem in
  the T0035 probe itself (the probe's tests pass on the seeded path). Do not
  change `eval_rag_injection`'s signature or behavior — the bug is in what the
  runner hands it.
- Out of scope: changing the 0.35 guardrail, changing the injection fixtures,
  or redesigning the live harness generally. Just make the seeded-store-on-live
  path real.
