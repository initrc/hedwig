from pathlib import Path

from app.ingest.source import EmailSource, LocalEmlSource, RawEmail

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
