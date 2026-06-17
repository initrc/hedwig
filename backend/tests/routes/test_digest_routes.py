"""Tests for POST /digest/run, the on-demand digest generation endpoint.

Every test overrides the store and pipeline-runner dependencies so no test
touches the real database or the network.  See ``tests/__init__.py`` for the
conventions around fakes and dependency overrides.
"""

from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.digest import Digest
from app.routes.digest_routes import (
    get_embed_fn,
    get_llm_client,
    get_pipeline_runner,
    get_store,
    get_vector_store,
)
from app.storage.digest_store import DigestStore
from tests.fakes import _digest, _digest_source, _digest_topic
from tests.rag.fakes import StubStore, stub_embed


def test_digest_run_returns_digest_and_persists(tmp_path: Path) -> None:
    """POST /digest/run ingests, pipelines, persists, and returns the digest.

    The pipeline runner is overridden with a stub that returns a pre-built
    ``Digest`` (built from ``tests.fakes`` factories), so no LLM calls are
    made.  The store is overridden with an in-memory database so persistence
    can be verified without touching disk.
    """
    # -- arrange: a single minimal .eml file --------------------------------
    eml = tmp_path / "test.eml"
    eml.write_text(
        "From: sender@example.com\r\n"
        "Subject: Test Subject\r\n"
        "Date: Mon, 15 Jun 2026 10:00:00 +0000\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=\"utf-8\"\r\n"
        "\r\n"
        "<html><body><p>Test body content.</p></body></html>\r\n"
    )

    # -- arrange: stub the store, pipeline runner, vector store, and embed fn
    mem_store = DigestStore(db_path=":memory:", check_same_thread=False)
    app.dependency_overrides[get_store] = lambda: mem_store

    expected = _digest(
        digest_date=date(2026, 6, 15),
        topics=[
            _digest_topic(
                label="Test Topic",
                summary="A test summary.",
                sources=[
                    _digest_source(
                        source_id="test.eml",
                        source="sender@example.com",
                        subject="Test Subject",
                        clean_text="Test body content.",
                        original_url=None,
                    )
                ],
                image=None,
            )
        ],
    )

    def _stub_pipeline(
        items: Any, *, date: Any = None, client: Any = None  # noqa: ARG001
    ) -> Digest:
        return expected

    app.dependency_overrides[get_pipeline_runner] = lambda: _stub_pipeline

    stub_store = StubStore()
    app.dependency_overrides[get_vector_store] = lambda: stub_store
    app.dependency_overrides[get_embed_fn] = lambda: stub_embed
    # The pipeline is stubbed so the client is never called; None is enough.
    app.dependency_overrides[get_llm_client] = lambda: None

    client = TestClient(app)

    # -- act -----------------------------------------------------------------
    response = client.post(
        "/digest/run",
        json={"samples_dir": str(tmp_path), "date": "2026-06-15"},
    )

    # -- assert: response ----------------------------------------------------
    assert response.status_code == 200

    body = response.json()
    assert body["date"] == "2026-06-15"
    assert len(body["topics"]) == 1

    topic = body["topics"][0]
    assert topic["label"] == "Test Topic"
    assert topic["summary"] == "A test summary."
    assert topic["image"] is None
    assert len(topic["sources"]) == 1

    source = topic["sources"][0]
    assert source["id"] == "test.eml"
    assert source["source"] == "sender@example.com"
    assert source["subject"] == "Test Subject"
    assert source["clean_text"] == "Test body content."

    # The JSON round-trips through the Digest model.
    reloaded = Digest.model_validate(body)
    assert reloaded == expected

    # -- assert: persistence -------------------------------------------------
    loaded = mem_store.load("2026-06-15")
    assert loaded is not None
    assert loaded == expected

    # -- assert: indexing ----------------------------------------------------
    assert stub_store.insert_calls == 1
    assert stub_store.chunk_count > 0
    # The source text "Test body content." is short, so it produces one chunk.
    indexed = stub_store.chunks[0]
    assert indexed.metadata["digest_date"] == "2026-06-15"
    assert indexed.metadata["topic_label"] == "Test Topic"
    assert indexed.metadata["source_id"] == "test.eml"
    assert indexed.metadata["source_subject"] == "Test Subject"
    assert indexed.metadata["chunk_index"] == 0

    # -- clean up ------------------------------------------------------------
    app.dependency_overrides.clear()
