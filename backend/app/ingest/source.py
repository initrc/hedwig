"""EmailSource abstraction and the offline LocalEmlSource implementation.

`EmailSource` decouples the rest of the pipeline from where email comes from.
The parser consumes `RawEmail` objects and does not care whether they were read
from local `.eml` files or fetched over IMAP.
"""

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
