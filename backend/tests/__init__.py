"""Tests for the Hedwig backend.

Conventions
-----------

**Fakes over mocks.**  ``tests/fakes.py`` holds shared test doubles.  Every
test that talks to the LLM should use ``QueuedFakeClient`` (or ``FakeClient``
for a single reply).  Tests that need domain objects (a ``Digest``, a
``ParsedEmail``, a ``DigestTopic``, etc.) should use the ``_digest``,
``_parsed_email``, ``_digest_topic``, and similar factories from fakes rather
than constructing models by hand.  This keeps tests short and consistent.

**Dependency overrides for FastAPI routes.**  Route tests use
``app.dependency_overrides`` to swap in stubs for the store and the pipeline
runner.  Always call ``app.dependency_overrides.clear()`` at the end of a test
so overrides never leak into the next one.

**In-memory SQLite for storage tests.**  Pass ``db_path=":memory:"`` (and
``check_same_thread=False`` for route tests) to ``DigestStore`` so every test
gets its own isolated database that disappears when the test ends.

**No real API calls.**  No test should ever reach the network.  If a new test
needs an LLM reply, queue it through ``QueuedFakeClient``.  If a test does not
care what the LLM returns, override the pipeline runner with a stub that
returns a pre-built ``Digest`` from the fakes factories.
"""
