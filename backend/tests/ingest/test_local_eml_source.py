from pathlib import Path

import pytest

from app.ingest.source import (
    EmailSource,
    LocalEmlSource,
    RawEmail,
    get_email_source,
    list_local_source_ids,
)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def test_local_eml_source_satisfies_protocol() -> None:
    source = LocalEmlSource(SAMPLES_DIR)
    assert isinstance(source, EmailSource)


def test_fetches_committed_samples_with_subjects() -> None:
    source = LocalEmlSource(SAMPLES_DIR)
    emails = list(source.fetch())

    assert emails, "expected committed samples/*.eml to yield messages"
    for email in emails:
        assert isinstance(email, RawEmail)
        assert email.source_id.endswith(".eml")
        subject = email.message["Subject"]
        assert subject and subject.strip(), f"empty Subject for {email.source_id}"


# ---------------------------------------------------------------------------
# list_local_source_ids (T0021)
# ---------------------------------------------------------------------------


def test_list_local_source_ids_matches_fetch_ids(tmp_path: Path) -> None:
    """`list_local_source_ids` returns the same ids `fetch` would yield, sorted."""
    (tmp_path / "b.eml").write_text(_minimal_eml("B"))
    (tmp_path / "a.eml").write_text(_minimal_eml("A"))
    (tmp_path / "readme.md").write_text("not an email")

    ids = list_local_source_ids(tmp_path)
    assert ids == ["a.eml", "b.eml"]

    fetched = [e.source_id for e in LocalEmlSource(tmp_path).fetch()]
    assert fetched == ids


def test_list_local_source_ids_empty_when_no_eml(tmp_path: Path) -> None:
    assert list_local_source_ids(tmp_path) == []


# ---------------------------------------------------------------------------
# get_email_source (T0021)
# ---------------------------------------------------------------------------


def test_get_email_source_defaults_to_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no EMAIL_SOURCE set, a LocalEmlSource is returned."""
    monkeypatch.delenv("EMAIL_SOURCE", raising=False)
    source = get_email_source(tmp_path)
    assert isinstance(source, LocalEmlSource)
    assert source.samples_dir == tmp_path


def test_get_email_source_samples_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_SOURCE", "samples")
    assert isinstance(get_email_source(tmp_path), LocalEmlSource)


def test_get_email_source_imap_not_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EMAIL_SOURCE=imap is the extension point for the later real-email task."""
    monkeypatch.setenv("EMAIL_SOURCE", "imap")
    with pytest.raises(NotImplementedError):
        get_email_source(tmp_path)


def test_get_email_source_unknown_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_SOURCE", "carrier-pigeon")
    with pytest.raises(ValueError, match="carrier-pigeon"):
        get_email_source(tmp_path)


def _minimal_eml(subject: str) -> str:
    return (
        "\r\n".join(
            [
                "From: sender@example.com",
                f"Subject: {subject}",
                "Date: Tue, 09 Jun 2026 10:00:00 +0000",
                "MIME-Version: 1.0",
                'Content-Type: text/html; charset="utf-8"',
                "",
                "<html><body><p>Body.</p></body></html>",
            ]
        )
        + "\r\n"
    )
