"""ImapSource: a thin IMAP fetcher satisfying the EmailSource interface.

Connects to an IMAP mailbox (Gmail in practice) over SSL, runs a server-side
search so we only download matching messages, and yields each as a `RawEmail`.
The IMAP UID is used as `source_id` so re-fetches map to stable identifiers.

Persistence, dedupe across runs, and OAuth are intentionally out of scope.
"""

from __future__ import annotations

import imaplib
import logging
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.parser import BytesParser
from email.policy import default

from dotenv import load_dotenv

from app.ingest.source import RawEmail

logger = logging.getLogger(__name__)

DEFAULT_PORT = 993
DEFAULT_MAILBOX = "INBOX"
DEFAULT_INITIAL_SINCE_DAYS = 1


class ImapSource:
    """Fetches messages from an IMAP mailbox as `RawEmail`s.

    Takes plain credentials (not env lookups) so it stays trivially testable;
    use `ImapSource.from_env()` to build one from `.env`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        since: date | None = None,
        senders: list[str] | None = None,
        mailbox: str = DEFAULT_MAILBOX,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.since = since
        self.senders = senders
        self.mailbox = mailbox

    @classmethod
    def from_env(
        cls,
        *,
        since: date | None = None,
        senders: list[str] | None = None,
        mailbox: str = DEFAULT_MAILBOX,
    ) -> ImapSource:
        """Build an `ImapSource` from IMAP_* variables in `.env` / the environment.

        `IMAP_SENDERS` (comma-separated newsletter sender emails) feeds the
        sender allowlist when the caller does not pass one. An empty
        `IMAP_SENDERS` is a loud error: an unfiltered mailbox fetch is exactly
        the failure mode the allowlist exists to prevent.

        `since` is the fetch start date. The caller should pass the last
        digest's date so a downtime gap is recovered in one fetch; when
        `since` is omitted (the very first run, no prior digest), it falls back
        to `IMAP_INITIAL_SINCE_DAYS` days back from today.
        """
        load_dotenv()
        if senders is None:
            senders = _parse_senders(os.environ.get("IMAP_SENDERS", ""))
        if not senders:
            raise ValueError(
                "IMAP_SENDERS is empty; set it to a comma-separated list of "
                "newsletter sender emails before enabling EMAIL_SOURCE=imap."
            )
        if since is None:
            since = _initial_since_from_env(os.environ.get("IMAP_INITIAL_SINCE_DAYS", ""))
        return cls(
            host=os.environ["IMAP_HOST"],
            port=int(os.environ.get("IMAP_PORT", str(DEFAULT_PORT))),
            username=os.environ["IMAP_USERNAME"],
            password=os.environ["IMAP_PASSWORD"],
            since=since,
            senders=senders,
            mailbox=mailbox,
        )

    def build_search_criteria(self) -> str:
        """Build the IMAP SEARCH criteria from the configured filters.

        Combines a `SINCE` date filter with an OR-chain over the sender list.
        Returns `ALL` when no filters are set. Exposed (and pure) so tests can
        assert on filter construction without touching the network.
        """
        clauses: list[str] = []
        if self.since is not None:
            # IMAP wants a "DD-Mon-YYYY" date, e.g. 14-Jun-2026.
            clauses.append(f"SINCE {self.since.strftime('%d-%b-%Y')}")
        if self.senders:
            clauses.append(_or_from_clause(self.senders))
        if not clauses:
            return "ALL"
        # Space-separated clauses are an implicit AND in IMAP.
        return " ".join(clauses)

    def fetch(self) -> Iterator[RawEmail]:
        """Connect, search, and yield each matching message as a `RawEmail`."""
        criteria = self.build_search_criteria()
        imap = imaplib.IMAP4_SSL(self.host, self.port)
        try:
            try:
                imap.login(self.username, self.password)
            except imaplib.IMAP4.error as exc:
                # Build our own message so the password never reaches the logs.
                raise RuntimeError(f"IMAP login failed for {self.username}") from exc
            imap.select(self.mailbox, readonly=True)

            status, data = imap.uid("SEARCH", criteria)
            if status != "OK":
                raise RuntimeError(f"IMAP search failed ({status}) with criteria: {criteria}")
            uids = data[0].split() if data and data[0] else []
            logger.info("IMAP search matched %d message(s) in %s", len(uids), self.mailbox)

            parser = BytesParser(policy=default)
            for uid in uids:
                status, msg_data = imap.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    logger.warning("failed to fetch UID %s (%s)", uid.decode(), status)
                    continue
                message = parser.parsebytes(msg_data[0][1])
                yield RawEmail(source_id=uid.decode(), message=message)
        finally:
            try:
                imap.logout()
            except OSError:
                pass


def _or_from_clause(senders: list[str]) -> str:
    """Build an OR-chain of `FROM` terms, e.g. `OR FROM "a" FROM "b"`.

    IMAP `OR` is a binary prefix operator, so N senders need N-1 leading ORs.
    """
    clause = f'FROM "{senders[0]}"'
    for sender in senders[1:]:
        clause = f'OR {clause} FROM "{sender}"'
    return clause


def _parse_senders(raw: str) -> list[str]:
    """Split a comma-separated sender list, dropping blanks and whitespace."""
    return [s.strip() for s in raw.split(",") if s.strip()]


def _initial_since_from_env(raw: str) -> date:
    """Turn the `IMAP_INITIAL_SINCE_DAYS` env var into a `date` that many days back.

    This is the fetch window for the very first run, when no prior digest
    exists to resume from. Defaults to `DEFAULT_INITIAL_SINCE_DAYS` when unset
    or blank. A non-integer value is a loud error so a typo doesn't silently
    widen the fetch window.
    """
    text = raw.strip()
    days = int(text) if text else DEFAULT_INITIAL_SINCE_DAYS
    return (datetime.now(UTC) - timedelta(days=days)).date()
