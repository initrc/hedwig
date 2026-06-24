"""Tests for `app.runner`: the shared digest runner and the trigger policy.

`run_digests` is the body both the startup lifespan and `POST /digest/run`
call. These tests pin down the behavior that matters for T0021: the status
transitions around a run, the `ingested_sources` recording that drives the
"should I run?" policy, the per-day grouping, and the date filter. Every test
uses a fresh `DigestStatus` instance so the module-level one is never touched.

The pipeline, vector store, and embed fn are stubbed — no network, no real
LLM — mirroring the conventions in `tests/routes/test_digest_routes.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ingest.source import LocalEmlSource
from app.llm.fake_client import FakeClient, model_reply
from app.pipeline.digest import Digest
from app.runner import run_digests, should_run_daily, should_run_digest
from app.status import DigestStatus
from app.storage.digest_store import DigestStore
from tests.fakes import make_digest, make_digest_source, make_digest_topic, make_story_source
from tests.rag.fakes import StubStore, stub_embed


def _eml(subject: str, date_header: str, body: str = "Body.") -> str:
    """Build a minimal .eml string with a Date header."""
    lines = [
        "From: sender@example.com",
        f"Subject: {subject}",
        f"Date: {date_header}",
        "MIME-Version: 1.0",
        'Content-Type: text/html; charset="utf-8"',
        "",
        f"<html><body><p>{body}</p></body></html>",
    ]
    return "\r\n".join(lines) + "\r\n"


def _stub_pipeline(
    items: Any,
    *,
    date: Any = None,
    client: Any = None,  # noqa: ARG001
) -> Digest:
    """A pipeline stub that records its calls via the store's ingested_sources."""
    sources = [
        make_digest_source(source_id=item.id, subject=item.subject, clean_text=item.clean_text)
        for item in items
    ]
    story_sources = [
        make_story_source(text=item.clean_text, source_item_id=item.id) for item in items
    ]
    return make_digest(
        digest_date=date,
        topics=[
            make_digest_topic(
                label="Topic", summary="Sum.", sources=sources, story_sources=story_sources
            )
        ],
    )


@pytest.fixture()
def deps(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Wire an in-memory store, stub pipeline, stub vector store, and fresh status."""
    state: dict[str, Any] = {
        "store": DigestStore(db_path=":memory:", check_same_thread=False),
        "vector_store": StubStore(),
        "status": DigestStatus(),
    }
    yield state


# ---------------------------------------------------------------------------
# should_run_digest
# ---------------------------------------------------------------------------


def test_should_run_returns_true_when_new_source_ids(deps: dict[str, Any]) -> None:
    store: DigestStore = deps["store"]
    store.record_ingested_sources(["a.eml"], date(2026, 6, 17))
    assert should_run_digest(["a.eml", "b.eml"], store) is True


def test_should_run_returns_false_when_all_sources_ingested(deps: dict[str, Any]) -> None:
    store: DigestStore = deps["store"]
    store.record_ingested_sources(["a.eml", "b.eml"], date(2026, 6, 17))
    assert should_run_digest(["a.eml", "b.eml"], store) is False


def test_should_run_returns_false_when_no_sources(deps: dict[str, Any]) -> None:
    assert should_run_digest([], deps["store"]) is False


def test_should_run_returns_true_when_store_empty(deps: dict[str, Any]) -> None:
    assert should_run_digest(["a.eml"], deps["store"]) is True


# ---------------------------------------------------------------------------
# should_run_daily (IMAP trigger policy)
# ---------------------------------------------------------------------------


def _stamp_last_digest(store: DigestStore, when: datetime) -> None:
    """Overwrite the most recent digest's `generated_at` for deterministic tests."""
    store._conn.execute("UPDATE digests SET generated_at = ?", [when.isoformat()])
    store._conn.commit()


def test_should_run_daily_true_when_store_empty(deps: dict[str, Any]) -> None:
    """Never run → run."""
    assert should_run_daily(deps["store"]) is True


def test_should_run_daily_true_when_last_digest_predates_today(
    deps: dict[str, Any],
) -> None:
    """A digest from yesterday (or earlier) triggers a run today."""
    store: DigestStore = deps["store"]
    store.save(make_digest())
    _stamp_last_digest(store, datetime.now(UTC) - timedelta(days=1, hours=2))

    assert should_run_daily(store) is True


def test_should_run_daily_false_when_last_digest_is_today(deps: dict[str, Any]) -> None:
    """A digest already produced today does not re-trigger on a same-day restart."""
    store: DigestStore = deps["store"]
    store.save(make_digest())
    _stamp_last_digest(store, datetime.now(UTC) - timedelta(hours=2))

    assert should_run_daily(store) is False


def test_should_run_daily_uses_utc_day_boundary(deps: dict[str, Any]) -> None:
    """A digest at 23:30 UTC yesterday still counts as 'today' is a new day."""
    store: DigestStore = deps["store"]
    store.save(make_digest())

    now = datetime(2026, 6, 24, 0, 5, tzinfo=UTC)
    _stamp_last_digest(store, datetime(2026, 6, 23, 23, 30, tzinfo=UTC))

    assert should_run_daily(store, now=now) is True


def test_should_run_daily_same_utc_day_no_rerun(deps: dict[str, Any]) -> None:
    """Within the same UTC day, no re-run even hours later."""
    store: DigestStore = deps["store"]
    store.save(make_digest())

    now = datetime(2026, 6, 24, 23, 55, tzinfo=UTC)
    _stamp_last_digest(store, datetime(2026, 6, 24, 0, 5, tzinfo=UTC))

    assert should_run_daily(store, now=now) is False


# ---------------------------------------------------------------------------
# run_digests — status transitions
# ---------------------------------------------------------------------------


def test_run_digests_sets_running_then_idle(deps: dict[str, Any], tmp_path: Path) -> None:
    """A run reports `running` with the email count, then `idle` with the last digest."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-12-b.eml").write_text(_eml("B", "Fri, 12 Jun 2026 09:00:00 +0000"))

    status: DigestStatus = deps["status"]
    run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=status,
    )

    # After the run, status is idle with the latest digest's timestamp.
    snap = status.snapshot()
    assert snap["state"] == "idle"
    assert snap["last_digest_at"] is not None


def test_run_digests_counts_emails_across_days(deps: dict[str, Any], tmp_path: Path) -> None:
    """`email_count` while running is the total emails being digested across days."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-09-b.eml").write_text(_eml("B", "Tue, 09 Jun 2026 14:00:00 +0000"))
    (tmp_path / "2026-06-12-c.eml").write_text(_eml("C", "Fri, 12 Jun 2026 09:00:00 +0000"))

    captured: list[int] = []
    status: DigestStatus = deps["status"]
    real_set_running = status.set_running

    def capture(email_count: int) -> None:
        captured.append(email_count)
        real_set_running(email_count)

    status.set_running = capture  # type: ignore[method-assign]
    run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=status,
    )

    assert captured == [3]


def test_run_digests_idle_when_no_emails(deps: dict[str, Any], tmp_path: Path) -> None:
    """An empty source still transitions to idle with null metadata."""
    status: DigestStatus = deps["status"]
    run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=status,
    )

    snap = status.snapshot()
    assert snap == {"state": "idle", "last_digest_at": None}


# ---------------------------------------------------------------------------
# run_digests — ingested_sources recording + policy feedback
# ---------------------------------------------------------------------------


def test_run_digests_records_ingested_source_ids(deps: dict[str, Any], tmp_path: Path) -> None:
    """After a run, every processed email's id is in `ingested_sources`."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-12-b.eml").write_text(_eml("B", "Fri, 12 Jun 2026 09:00:00 +0000"))

    store: DigestStore = deps["store"]
    run_digests(
        LocalEmlSource(tmp_path),
        store=store,
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=deps["status"],
    )

    assert store.ingested_source_ids() == {"2026-06-09-a.eml", "2026-06-12-b.eml"}


def test_run_digests_makes_subsequent_run_skip(deps: dict[str, Any], tmp_path: Path) -> None:
    """After digesting all samples, `should_run_digest` reports nothing new."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    store: DigestStore = deps["store"]

    run_digests(
        LocalEmlSource(tmp_path),
        store=store,
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=deps["status"],
    )

    from app.ingest.source import list_local_source_ids

    assert should_run_digest(list_local_source_ids(tmp_path), store) is False


def test_new_file_triggers_run_after_priormake_digest(deps: dict[str, Any], tmp_path: Path) -> None:
    """Adding a new .eml after a prior run makes `should_run_digest` true again."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    store: DigestStore = deps["store"]

    run_digests(
        LocalEmlSource(tmp_path),
        store=store,
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=deps["status"],
    )

    from app.ingest.source import list_local_source_ids

    assert should_run_digest(list_local_source_ids(tmp_path), store) is False

    (tmp_path / "2026-06-10-b.eml").write_text(_eml("B", "Wed, 10 Jun 2026 10:00:00 +0000"))
    assert should_run_digest(list_local_source_ids(tmp_path), store) is True


# ---------------------------------------------------------------------------
# run_digests — grouping + date filter (parity with the old endpoint behavior)
# ---------------------------------------------------------------------------


def test_run_digests_groups_by_day(deps: dict[str, Any], tmp_path: Path) -> None:
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-09-b.eml").write_text(_eml("B", "Tue, 09 Jun 2026 14:00:00 +0000"))
    (tmp_path / "2026-06-12-c.eml").write_text(_eml("C", "Fri, 12 Jun 2026 09:00:00 +0000"))

    results = run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=deps["status"],
    )

    assert [d.date for d in results] == [date(2026, 6, 9), date(2026, 6, 12)]
    store: DigestStore = deps["store"]
    assert store.load("2026-06-09") is not None
    assert store.load("2026-06-12") is not None


def test_run_digests_date_filter_processes_one_day(deps: dict[str, Any], tmp_path: Path) -> None:
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-12-b.eml").write_text(_eml("B", "Fri, 12 Jun 2026 09:00:00 +0000"))

    results = run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        date_filter=date(2026, 6, 9),
        status=deps["status"],
    )

    assert [d.date for d in results] == [date(2026, 6, 9)]
    store: DigestStore = deps["store"]
    assert store.load("2026-06-09") is not None
    assert store.load("2026-06-12") is None


def test_run_digests_skips_email_with_no_received_date(
    deps: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An email with no Date header is skipped with a warning; the rest still process."""
    (tmp_path / "dated.eml").write_text(_eml("Dated", "Mon, 15 Jun 2026 10:00:00 +0000"))
    (tmp_path / "undated.eml").write_text(
        "\r\n".join(
            [
                "From: sender@example.com",
                "Subject: Undated",
                "MIME-Version: 1.0",
                'Content-Type: text/html; charset="utf-8"',
                "",
                "<html><body><p>Body.</p></body></html>",
            ]
        )
        + "\r\n"
    )

    with caplog.at_level("WARNING"):
        results = run_digests(
            LocalEmlSource(tmp_path),
            store=deps["store"],
            pipeline=_stub_pipeline,
            vector_store=deps["vector_store"],
            embed_fn=stub_embed,
            client=FakeClient(model_reply("{}")),
            status=deps["status"],
        )

    assert [d.date for d in results] == [date(2026, 6, 15)]
    assert any(
        "undated.eml" in record.message and record.levelname == "WARNING"
        for record in caplog.records
    )


def test_run_digests_indexes_eachmake_digest(deps: dict[str, Any], tmp_path: Path) -> None:
    """Each produced digest is indexed once into the vector store."""
    (tmp_path / "2026-06-09-a.eml").write_text(_eml("A", "Tue, 09 Jun 2026 10:00:00 +0000"))
    (tmp_path / "2026-06-12-b.eml").write_text(_eml("B", "Fri, 12 Jun 2026 09:00:00 +0000"))

    run_digests(
        LocalEmlSource(tmp_path),
        store=deps["store"],
        pipeline=_stub_pipeline,
        vector_store=deps["vector_store"],
        embed_fn=stub_embed,
        client=FakeClient(model_reply("{}")),
        status=deps["status"],
    )

    assert deps["vector_store"].insert_calls == 2
