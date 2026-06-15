"""Smoke test: fetch from the configured IMAP mailbox and print subjects.

Not part of the automated suite — it hits the live network. Run it manually
once `.env` has real IMAP_* credentials (a Gmail app password):

    uv run python scripts/fetch_imap_smoke.py

Defaults to the last 14 days of INBOX to avoid pulling the whole mailbox.
"""

from datetime import date, timedelta

from app.ingest.imap_source import ImapSource

SINCE_DAYS = 14


def main() -> None:
    since = date.today() - timedelta(days=SINCE_DAYS)
    source = ImapSource.from_env(since=since)
    print(f"Fetching messages since {since.isoformat()} from {source.mailbox}...")

    count = 0
    for email in source.fetch():
        count += 1
        print(f"  [{email.source_id}] {email.message['Subject']}")

    print(f"Done. Fetched {count} message(s).")
    if count == 0:
        print("No messages matched — widen the date range or check credentials.")


if __name__ == "__main__":
    main()
