"""Save and load `Digest` objects to a local SQLite database.

The store reads and writes the full digest as JSON in a single table — no ORM,
no per-field mapping. Callers get back a validated `Digest` model, not a plain
dict or row. The stdlib ``sqlite3`` module is the only dependency; no extra
packages needed.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from app.pipeline.digest import Digest

# Relative to the current working directory, matching how dump.py's
# DEFAULT_OUTPUT works.  The caller (e.g., a CLI or the test suite) is
# expected to run from the backend/ directory or pass an explicit path.
DEFAULT_DB_PATH = Path("db/hedwig.db")


class DigestStore:
    """Persist `Digest` objects to SQLite, one row per digest.

    The table is created on construction with ``CREATE TABLE IF NOT EXISTS``
    so callers don't need a separate migration step.  Pass ``":memory:"`` as
    the path for tests that need an isolated store that disappears when the
    connection closes.

    A digest's ``id`` is its ISO-format date string (e.g. ``"2026-06-15"``).
    There is one digest per calendar date, so saving a digest with a date that
    already exists overwrites the old row (upsert semantics).
    """

    def __init__(
        self,
        *,
        db_path: str | Path = DEFAULT_DB_PATH,
        check_same_thread: bool = True,
    ) -> None:
        db_path = Path(db_path) if isinstance(db_path, str) else db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id      TEXT PRIMARY KEY,
                date    TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # -- public API -------------------------------------------------------------

    def save(self, digest: Digest) -> str:
        """Persist a digest and return its id (the ISO-format date string).

        If a digest with the same date already exists it is replaced so every
        caller sees the latest version (upsert).
        """
        digest_id = digest.date.isoformat()
        payload = digest.model_dump_json()
        self._conn.execute(
            """
            INSERT INTO digests (id, date, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                date = excluded.date,
                payload_json = excluded.payload_json
            """,
            (digest_id, digest_id, payload),
        )
        self._conn.commit()
        return digest_id

    def load(self, digest_id: str) -> Digest | None:
        """Load a digest by id (an ISO-format date string), or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT payload_json FROM digests WHERE id = ?", [digest_id]
        ).fetchone()
        if row is None:
            return None
        return Digest.model_validate_json(row["payload_json"])

    def load_by_date(self, target_date: date) -> Digest | None:
        """Load a digest by its calendar date, or ``None`` if not found."""
        return self.load(target_date.isoformat())

    def list_recent(self, limit: int = 10) -> list[Digest]:
        """Return the most recent digests, newest date first."""
        rows = self._conn.execute(
            "SELECT payload_json FROM digests ORDER BY date DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [Digest.model_validate_json(row["payload_json"]) for row in rows]
