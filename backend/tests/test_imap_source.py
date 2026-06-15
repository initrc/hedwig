from datetime import date
from typing import Any

import pytest

from app.ingest.imap_source import ImapSource
from app.ingest.source import EmailSource, RawEmail


def test_imap_source_satisfies_protocol() -> None:
    source = ImapSource("imap.gmail.com", 993, "user@gmail.com", "pw")
    assert isinstance(source, EmailSource)


def test_search_criteria_is_all_when_no_filters() -> None:
    source = ImapSource("h", 993, "u", "pw")
    assert source.build_search_criteria() == "ALL"


def test_search_criteria_with_since_only() -> None:
    source = ImapSource("h", 993, "u", "pw", since=date(2026, 6, 14))
    assert source.build_search_criteria() == "SINCE 14-Jun-2026"


def test_search_criteria_with_single_sender() -> None:
    source = ImapSource("h", 993, "u", "pw", senders=["a@x.com"])
    assert source.build_search_criteria() == 'FROM "a@x.com"'


def test_search_criteria_with_multiple_senders() -> None:
    source = ImapSource("h", 993, "u", "pw", senders=["a@x.com", "b@y.com", "c@z.com"])
    assert source.build_search_criteria() == 'OR OR FROM "a@x.com" FROM "b@y.com" FROM "c@z.com"'


def test_search_criteria_combines_since_and_senders() -> None:
    source = ImapSource("h", 993, "u", "pw", since=date(2026, 6, 1), senders=["a@x.com", "b@y.com"])
    assert source.build_search_criteria() == 'SINCE 01-Jun-2026 OR FROM "a@x.com" FROM "b@y.com"'


# --- fetch() with a mocked IMAP client (no live network) ---

_RAW_EMAIL = (
    b"From: Alpha Signal <news@alpha.com>\r\n"
    b"Subject: Weekly digest\r\n"
    b"Date: Sat, 14 Jun 2026 09:00:00 +0000\r\n"
    b"\r\n"
    b"Body text\r\n"
)


class FakeIMAP4_SSL:
    """Records calls and returns canned responses for fetch() tests."""

    instances: list["FakeIMAP4_SSL"] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.login_args: tuple[str, str] | None = None
        self.select_args: tuple[str, bool] | None = None
        self.uid_calls: list[tuple[Any, ...]] = []
        self.logged_out = False
        FakeIMAP4_SSL.instances.append(self)

    def login(self, user: str, password: str) -> tuple[str, list[Any]]:
        self.login_args = (user, password)
        return ("OK", [b"LOGIN completed"])

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[Any]]:
        self.select_args = (mailbox, readonly)
        return ("OK", [b"1"])

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.uid_calls.append((command, *args))
        if command == "SEARCH":
            return ("OK", [b"101 102"])
        if command == "FETCH":
            return ("OK", [(b"1 (RFC822 {0}", _RAW_EMAIL), b")"])
        raise AssertionError(f"unexpected uid command {command}")

    def logout(self) -> tuple[str, list[Any]]:
        self.logged_out = True
        return ("BYE", [b"logging out"])


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[FakeIMAP4_SSL]:
    FakeIMAP4_SSL.instances = []
    monkeypatch.setattr("app.ingest.imap_source.imaplib.IMAP4_SSL", FakeIMAP4_SSL)
    return FakeIMAP4_SSL


def test_fetch_plumbs_credentials_and_mailbox(fake_imap: type[FakeIMAP4_SSL]) -> None:
    source = ImapSource("imap.gmail.com", 993, "user@gmail.com", "secret", mailbox="INBOX")

    list(source.fetch())

    client = fake_imap.instances[0]
    assert client.host == "imap.gmail.com"
    assert client.port == 993
    assert client.login_args == ("user@gmail.com", "secret")
    assert client.select_args == ("INBOX", True)
    assert client.logged_out is True


def test_fetch_passes_built_criteria_to_search(fake_imap: type[FakeIMAP4_SSL]) -> None:
    source = ImapSource("h", 993, "u", "pw", since=date(2026, 6, 1), senders=["a@x.com"])

    list(source.fetch())

    search_calls = [c for c in fake_imap.instances[0].uid_calls if c[0] == "SEARCH"]
    assert search_calls == [("SEARCH", 'SINCE 01-Jun-2026 FROM "a@x.com"')]


def test_fetch_yields_raw_emails_keyed_by_uid(fake_imap: type[FakeIMAP4_SSL]) -> None:
    source = ImapSource("h", 993, "u", "pw")

    emails = list(source.fetch())

    assert [e.source_id for e in emails] == ["101", "102"]
    for email in emails:
        assert isinstance(email, RawEmail)
        assert email.message["Subject"] == "Weekly digest"
