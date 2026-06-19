"""Tests for `app.status.DigestStatus`, the thread-safe run-state holder.

The status object is shared between the background runner (writer) and the
`/status` endpoint (reader), so these tests pin down the two snapshot shapes
and the transitions between them. A fresh instance is used per test so the
module-level `digest_status` never leaks state across tests.
"""

from datetime import datetime

from app.status import DigestStatus


def test_initial_snapshot_is_idle_with_null_timestamp() -> None:
    status = DigestStatus()
    assert status.snapshot() == {"state": "idle", "last_digest_at": None}


def test_set_running_reports_email_count() -> None:
    status = DigestStatus()
    status.set_running(7)
    assert status.snapshot() == {"state": "running", "email_count": 7}


def test_set_idle_records_last_digest_timestamp() -> None:
    status = DigestStatus()
    status.set_running(3)
    status.set_idle(datetime(2026, 6, 18, 8, 0, 0))
    assert status.snapshot() == {
        "state": "idle",
        "last_digest_at": "2026-06-18T08:00:00",
    }


def test_set_idle_with_null_clears_running_state() -> None:
    status = DigestStatus()
    status.set_running(3)
    status.set_idle(None)
    assert status.snapshot() == {"state": "idle", "last_digest_at": None}


def test_set_running_clears_previous_idle_timestamp() -> None:
    status = DigestStatus()
    status.set_idle(datetime(2026, 6, 17, 8, 0, 0))
    status.set_running(1)
    assert status.snapshot() == {"state": "running", "email_count": 1}
