"""EmailSource abstraction and the offline LocalEmlSource implementation.

`EmailSource` decouples the rest of the pipeline from where email comes from.
The parser consumes `RawEmail` objects and does not care whether they were read
from local `.eml` files or fetched over IMAP.

`get_email_source` picks an implementation from the `EMAIL_SOURCE` env var:
`samples` (the default) reads the committed `.eml` files, `imap` will read a
real mailbox (implemented in a later task). Callers that want a specific source
can construct `LocalEmlSource` / `ImapSource` directly.
"""

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawEmail:
    """A raw email message paired with a stable identifier.

    `source_id` is stable per source so downstream stages can dedupe and
    reference messages: the filename for local files, the IMAP UID for remote.
    """

    source_id: str
    message: Message


@runtime_checkable
class EmailSource(Protocol):
    """Yields raw email messages, decoupled from their origin."""

    def fetch(self) -> Iterable[RawEmail]:
        """Yield each available message as a `RawEmail`."""
        ...


class LocalEmlSource:
    """Reads `.eml` files from a directory and yields them as `RawEmail`s."""

    def __init__(self, samples_dir: Path) -> None:
        self.samples_dir = samples_dir

    def fetch(self) -> Iterator[RawEmail]:
        parser = BytesParser(policy=default)
        for path in sorted(self.samples_dir.glob("*.eml")):
            message = parser.parsebytes(path.read_bytes())
            yield RawEmail(source_id=path.name, message=message)


def list_local_source_ids(samples_dir: Path) -> list[str]:
    """Return the sorted filenames of every `.eml` under ``samples_dir``.

    These are the `source_id`s `LocalEmlSource` would yield, without paying the
    cost of reading and parsing each file. The startup runner uses this to ask
    "are there sample emails not yet digested?" without parsing them all first.
    """
    return sorted(path.name for path in samples_dir.glob("*.eml"))


def get_email_source(samples_dir: Path) -> EmailSource:
    """Build the `EmailSource` selected by the `EMAIL_SOURCE` env var.

    `EMAIL_SOURCE=samples` (the default) returns a `LocalEmlSource` pointed at
    `samples_dir`. `EMAIL_SOURCE=imap` will return an `ImapSource.from_env()`
    in a later task; for now it raises `NotImplementedError` so the choice is
    explicit and the extension point is visible.
    """
    choice = os.environ.get("EMAIL_SOURCE", "samples").strip().lower()
    if choice == "samples":
        return LocalEmlSource(samples_dir)
    if choice == "imap":
        # Real-email ingestion is a later task; see T0021 implementation notes.
        raise NotImplementedError("EMAIL_SOURCE=imap is not implemented yet")
    raise ValueError(f"Unknown EMAIL_SOURCE {choice!r} (expected 'samples' or 'imap')")
