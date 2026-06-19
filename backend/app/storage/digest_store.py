"""Save and load `Digest` objects to a local SQLite database.

The store reads and writes the full digest as JSON in a single table — no ORM,
no per-field mapping. Callers get back a validated `Digest` model, not a plain
dict or row. The stdlib ``sqlite3`` module is the only dependency; no extra
packages needed.

Two tables are maintained:

- ``digests`` — one row per calendar date, the full digest as JSON plus a
  ``generated_at`` timestamp recording when it was last produced.
- ``ingested_sources`` — one row per source id (a sample filename or IMAP UID)
  that has already been folded into a digest. The startup runner uses this to
  decide whether there is anything new to digest.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
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
        check_same_thread: bool = False,
    ) -> None:
        db_path = Path(db_path) if isinstance(db_path, str) else db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id           TEXT PRIMARY KEY,
                date         TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingested_sources (
                source_id    TEXT PRIMARY KEY,
                digest_date  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # -- public API -------------------------------------------------------------

    def save(self, digest: Digest) -> str:
        """Persist a digest and return its id (the ISO-format date string).

        If a digest with the same date already exists it is replaced so every
        caller sees the latest version (upsert). ``generated_at`` is stamped
        with the current UTC time on every save.
        """
        digest_id = digest.date.isoformat()
        payload = digest.model_dump_json()
        generated_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO digests (id, date, payload_json, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                date = excluded.date,
                payload_json = excluded.payload_json,
                generated_at = excluded.generated_at
            """,
            (digest_id, digest_id, payload, generated_at),
        )
        self._conn.commit()
        return digest_id

    def record_ingested_sources(self, source_ids: list[str], digest_date: date) -> None:
        """Mark each source id as folded into the digest for ``digest_date``.

        Upserts so a source reprocessed on a later run updates its recorded
        digest date. Called by the runner after a digest is saved.
        """
        if not source_ids:
            return
        digest_date_str = digest_date.isoformat()
        self._conn.executemany(
            """
            INSERT INTO ingested_sources (source_id, digest_date)
            VALUES (?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                digest_date = excluded.digest_date
            """,
            [(sid, digest_date_str) for sid in source_ids],
        )
        self._conn.commit()

    def ingested_source_ids(self) -> set[str]:
        """Return every source id that has been folded into some digest."""
        rows = self._conn.execute("SELECT source_id FROM ingested_sources").fetchall()
        return {row["source_id"] for row in rows}

    def last_digest_at(self) -> datetime | None:
        """Return the ``generated_at`` timestamp of the most recently produced digest.

        ``None`` when no digest has ever been saved. Used to populate the
        ``idle`` status so the frontend can show how stale the content is.
        """
        row = self._conn.execute(
            "SELECT generated_at FROM digests ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        if row is None or row["generated_at"] is None:
            return None
        return datetime.fromisoformat(row["generated_at"])

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
