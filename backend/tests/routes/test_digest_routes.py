"""Tests for POST /digest/run, the on-demand digest generation endpoint.

Every test overrides the store and pipeline-runner dependencies so no test
touches the real database or the network. See ``tests/__init__.py`` for the
conventions around fakes and dependency overrides.

The endpoint groups parsed emails by the UTC calendar day of their
``received_at`` and runs the pipeline once per day, returning a list of
digests. These tests cover the three paths that matter: multi-day grouping,
single-day filtering via the ``date`` field, and the skip-with-warning path
for emails that have no parseable ``Date`` header.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
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
from tests.fakes import make_digest, make_digest_source, make_digest_topic
from tests.rag.fakes import StubStore, stub_embed


def _eml(subject: str, date_header: str | None, body: str = "Body.") -> str:
    """Build a minimal .eml string. Omit the Date header when ``date_header`` is None."""
    lines = [
        "From: sender@example.com",
        f"Subject: {subject}",
    ]
    if date_header is not None:
        lines.append(f"Date: {date_header}")
    lines += [
        "MIME-Version: 1.0",
        'Content-Type: text/html; charset="utf-8"',
        "",
        f"<html><body><p>{body}</p></body></html>",
    ]
    return "\r\n".join(lines) + "\r\n"


@pytest.fixture()
def stubbed_deps() -> Iterator[dict[str, Any]]:
    """Wire in-memory store, stub pipeline, stub vector store, and stub embed fn.

    Returns a holder the test reads back to inspect pipeline calls and the
    in-memory store. Cleans up ``app.dependency_overrides`` on teardown.
    """
    state: dict[str, Any] = {
        "pipeline_calls": [],  # list of (date, [ParsedEmail]) per pipeline invocation
        "store": DigestStore(db_path=":memory:", check_same_thread=False),
        "vector_store": StubStore(),
    }

    def _stub_pipeline(
        items: Any,
        *,
        date: Any = None,
        client: Any = None,  # noqa: ARG001
    ) -> Digest:
        state["pipeline_calls"].append((date, list(items)))
        sources = [
            make_digest_source(
                source_id=item.id,
                source=item.source,
                subject=item.subject,
                clean_text=item.clean_text,
                original_url=item.original_url,
            )
            for item in items
        ]
        return make_digest(
            digest_date=date,
            topics=[make_digest_topic(label="Topic", summary="Sum.", sources=sources)],
        )

    app.dependency_overrides[get_store] = lambda: state["store"]
    app.dependency_overrides[get_pipeline_runner] = lambda: _stub_pipeline
    app.dependency_overrides[get_vector_store] = lambda: state["vector_store"]
    app.dependency_overrides[get_embed_fn] = lambda: stub_embed
    # The pipeline is stubbed so the client is never called; None is enough.
    app.dependency_overrides[get_llm_client] = lambda: None

    yield state

    app.dependency_overrides.clear()


def test_digest_run_groups_emails_by_day(stubbed_deps: dict[str, Any], tmp_path: Path) -> None:
    """POST /digest/run with no date produces one digest per received day.

    Three emails across two days: two on 2026-06-09, one on 2026-06-12. The
    pipeline runs once per day with that day's emails and date, and each
    digest is persisted and indexed.
    """
    (tmp_path / "2026-06-09-a.eml").write_text(
        _eml("A", "Tue, 09 Jun 2026 10:00:00 +0000", "Body A.")
    )
    (tmp_path / "2026-06-09-b.eml").write_text(
        _eml("B", "Tue, 09 Jun 2026 14:00:00 +0000", "Body B.")
    )
    (tmp_path / "2026-06-12-c.eml").write_text(
        _eml("C", "Fri, 12 Jun 2026 09:00:00 +0000", "Body C.")
    )

    client = TestClient(app)
    response = client.post("/digest/run", json={"samples_dir": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert [d["date"] for d in body] == ["2026-06-09", "2026-06-12"]

    # The pipeline saw one call per day, with the right items and date.
    calls = stubbed_deps["pipeline_calls"]
    assert [c[0] for c in calls] == [date(2026, 6, 9), date(2026, 6, 12)]
    assert [item.id for item in calls[0][1]] == ["2026-06-09-a.eml", "2026-06-09-b.eml"]
    assert [item.id for item in calls[1][1]] == ["2026-06-12-c.eml"]

    # Each digest was persisted under its own day.
    store: DigestStore = stubbed_deps["store"]
    assert store.load("2026-06-09") is not None
    assert store.load("2026-06-12") is not None

    # Each digest was indexed once (one insert call per index_digest).
    assert stubbed_deps["vector_store"].insert_calls == 2
    assert stubbed_deps["vector_store"].chunk_count == 3


def test_digest_run_filters_to_requested_date(stubbed_deps: dict[str, Any], tmp_path: Path) -> None:
    """POST /digest/run with a date processes only emails received on that day.

    The same three-email folder as the grouping test, but the request pins
    ``date`` to 2026-06-09. The response is a one-element list and only that
    day's two emails reach the pipeline.
    """
    (tmp_path / "2026-06-09-a.eml").write_text(
        _eml("A", "Tue, 09 Jun 2026 10:00:00 +0000", "Body A.")
    )
    (tmp_path / "2026-06-09-b.eml").write_text(
        _eml("B", "Tue, 09 Jun 2026 14:00:00 +0000", "Body B.")
    )
    (tmp_path / "2026-06-12-c.eml").write_text(
        _eml("C", "Fri, 12 Jun 2026 09:00:00 +0000", "Body C.")
    )

    client = TestClient(app)
    response = client.post(
        "/digest/run",
        json={"samples_dir": str(tmp_path), "date": "2026-06-09"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [d["date"] for d in body] == ["2026-06-09"]

    calls = stubbed_deps["pipeline_calls"]
    assert len(calls) == 1
    assert calls[0][0] == date(2026, 6, 9)
    assert [item.id for item in calls[0][1]] == ["2026-06-09-a.eml", "2026-06-09-b.eml"]

    # The other day was never persisted.
    store: DigestStore = stubbed_deps["store"]
    assert store.load("2026-06-09") is not None
    assert store.load("2026-06-12") is None
    assert stubbed_deps["vector_store"].insert_calls == 1


def test_digest_run_filters_to_day_with_no_emails_returns_empty(
    stubbed_deps: dict[str, Any], tmp_path: Path
) -> None:
    """A date filter that matches no emails returns an empty list, not an error."""
    (tmp_path / "2026-06-09-a.eml").write_text(
        _eml("A", "Tue, 09 Jun 2026 10:00:00 +0000", "Body A.")
    )

    client = TestClient(app)
    response = client.post(
        "/digest/run",
        json={"samples_dir": str(tmp_path), "date": "2026-06-12"},
    )

    assert response.status_code == 200
    assert response.json() == []
    assert stubbed_deps["pipeline_calls"] == []


def test_digest_run_skips_email_with_no_received_date(
    stubbed_deps: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An email with no Date header is skipped with a warning; the rest still process.

    The undated email must not be folded into an arbitrary day — only the dated
    email produces a digest.
    """
    (tmp_path / "dated.eml").write_text(_eml("Dated", "Mon, 15 Jun 2026 10:00:00 +0000"))
    (tmp_path / "undated.eml").write_text(_eml("Undated", None))

    client = TestClient(app)
    with caplog.at_level("WARNING"):
        response = client.post("/digest/run", json={"samples_dir": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert [d["date"] for d in body] == ["2026-06-15"]

    calls = stubbed_deps["pipeline_calls"]
    assert len(calls) == 1
    assert [item.id for item in calls[0][1]] == ["dated.eml"]

    # The skip was logged with the dropped email's source_id.
    assert any(
        "undated.eml" in record.message and record.levelname == "WARNING"
        for record in caplog.records
    )
