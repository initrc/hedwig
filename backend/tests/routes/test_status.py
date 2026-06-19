"""Tests for GET /status, the digest-run status endpoint.

The endpoint reads the module-level `digest_status` object, which the startup
runner and `/digest/run` both write. These tests cover the two shapes the
frontend renders: `running` (with an email count) and `idle` (with the last
digest's timestamp, or null when no digest exists yet).
"""

from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.status import digest_status

client = TestClient(app)


def test_status_returns_idle_when_no_run_in_progress() -> None:
    digest_status.set_idle(None)
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"state": "idle", "last_digest_at": None}


def test_status_returns_running_with_email_count() -> None:
    digest_status.set_running(5)
    try:
        response = client.get("/status")
    finally:
        digest_status.set_idle(None)

    assert response.status_code == 200
    assert response.json() == {"state": "running", "email_count": 5}


def test_status_returns_idle_with_last_digest_timestamp() -> None:
    digest_status.set_idle(datetime(2026, 6, 18, 9, 30, 0))
    try:
        response = client.get("/status")
    finally:
        digest_status.set_idle(None)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "idle"
    assert body["last_digest_at"] == "2026-06-18T09:30:00"
