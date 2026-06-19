"""In-memory digest run status, reported to the frontend via ``GET /status``.

The status object is process-local and reset on every startup, which matches
the product model: the backend digests once a day and the frontend treats each
browser session as a fresh view, polling only while a run is in progress.

Two shapes are exposed:

- ``running`` — a digest is being generated. Carries the number of emails the
  run ingested so the UI can say "Generating digest from N emails…".
- ``idle`` — no run in progress. Carries ``last_digest_at``, the timestamp of
  the most recent finished digest, or ``None`` when no digest has been produced
  yet. This tells the user how stale the content they are looking at is.

The lock keeps the read in the request handler consistent with the writes the
background runner makes; the runner runs in a separate thread, so the HTTP
thread must never observe a half-updated state.
"""

from __future__ import annotations

import threading
from datetime import datetime


class DigestStatus:
    """Thread-safe holder for the current digest run state.

    A single module-level instance (``digest_status``) is shared between the
    startup runner and the ``/status`` endpoint. The runner calls
    ``set_running`` at the start of a run and ``set_idle`` when it finishes; the
    endpoint calls ``snapshot`` to read a consistent copy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._email_count: int | None = None
        self._last_digest_at: datetime | None = None

    def set_running(self, email_count: int) -> None:
        """Mark a digest run as in progress with the number of emails ingested."""
        with self._lock:
            self._state = "running"
            self._email_count = email_count
            self._last_digest_at = None

    def set_idle(self, last_digest_at: datetime | None) -> None:
        """Mark the run as finished, recording when the last digest was produced.

        ``None`` means no digest has been produced yet (either the backend just
        started with an empty store, or a run produced no digests).
        """
        with self._lock:
            self._state = "idle"
            self._email_count = None
            self._last_digest_at = last_digest_at

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-serializable copy of the current status."""
        with self._lock:
            if self._state == "running":
                return {
                    "state": "running",
                    "email_count": self._email_count,
                }
            return {
                "state": "idle",
                "last_digest_at": (
                    self._last_digest_at.isoformat() if self._last_digest_at else None
                ),
            }


digest_status = DigestStatus()
