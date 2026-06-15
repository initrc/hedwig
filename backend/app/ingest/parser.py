"""Parse a `RawEmail` into a normalized `ParsedEmail`.

The parser is the boundary between messy newsletter email and the clean,
typed input the downstream LLM steps consume. It:

- extracts plain readable text from the HTML body (readability + BeautifulSoup),
  falling back to the text/plain part when there is no HTML;
- gathers *candidate* images (it deliberately does not pick a "best" one) while
  dropping logos and tracking pixels;
- pulls a "View in browser" style link into `original_url` when present.

Transfer-encoding (quoted-printable / base64) is decoded by the stdlib email
package via `get_content()`, so the parser only ever sees decoded text.
"""

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import cast

from bs4 import BeautifulSoup
from pydantic import BaseModel
from readability import Document

from app.ingest.source import RawEmail

# Below this many pixels in a known dimension an image is a logo, icon, or
# tracking pixel rather than real content.
MIN_IMAGE_DIMENSION = 100

# Link text that signals a "read this on the web" link, lower-cased.
_ORIGINAL_URL_HINTS = (
    "view in browser",
    "view this email in your browser",
    "view this in your browser",
    "view online",
    "view in your browser",
    "read online",
    "read on the web",
    "open in browser",
    "web version",
    "online version",
)


class CandidateImage(BaseModel):
    """An image referenced by the email, kept as a candidate for later selection.

    `alt` is always a string (possibly empty). `width`/`height` are the pixel
    dimensions from the HTML attributes, or `None` when the email omits them.
    """

    url: str
    alt: str = ""
    width: int | None = None
    height: int | None = None


class ParsedEmail(BaseModel):
    """A single newsletter email normalized for downstream processing."""

    id: str
    source: str
    subject: str
    received_at: datetime | None
    clean_text: str
    candidate_images: list[CandidateImage]
    original_url: str | None


def parse(raw: RawEmail) -> ParsedEmail:
    """Normalize a `RawEmail` into a `ParsedEmail`."""
    # LocalEmlSource/ImapSource parse with policy=default, which yields the
    # modern EmailMessage API (get_body / get_content) the helpers below rely on.
    message = cast(EmailMessage, raw.message)
    html, plain = _extract_bodies(message)

    if html is not None:
        clean_text = _html_to_text(html)
        candidate_images = _collect_images(html)
        original_url = _find_original_url(html)
    else:
        clean_text = _collapse_whitespace(plain or "")
        candidate_images = []
        original_url = None

    return ParsedEmail(
        id=raw.source_id,
        source=_extract_source(message),
        subject=_header_text(message, "Subject"),
        received_at=_extract_received_at(message),
        clean_text=clean_text,
        candidate_images=candidate_images,
        original_url=original_url,
    )


def _extract_bodies(message: EmailMessage) -> tuple[str | None, str | None]:
    """Return the (html, plain) bodies, decoded, either may be ``None``.

    ``get_body`` understands multipart/alternative and nested structures, so
    the HTML part need not come first (or be at the top level).
    """
    html_part = message.get_body(preferencelist=("html",))
    plain_part = message.get_body(preferencelist=("plain",))
    html = html_part.get_content() if html_part is not None else None
    plain = plain_part.get_content() if plain_part is not None else None
    return html, plain


def _html_to_text(html: str) -> str:
    """Strip HTML to plain, whitespace-collapsed readable text."""
    try:
        article_html = Document(html).summary()
    except Exception:
        # readability raises on empty/degenerate HTML; fall back to the raw body.
        article_html = html
    text = BeautifulSoup(article_html, "html.parser").get_text(separator=" ")
    return _collapse_whitespace(text)


def _collect_images(html: str) -> list[CandidateImage]:
    """Collect candidate images from the full HTML body.

    Images are read from the original HTML (not the readability summary, which
    discards most of them). Logos, icons, and tracking pixels are filtered out.
    """
    soup = BeautifulSoup(html, "html.parser")
    images: list[CandidateImage] = []
    for img in soup.find_all("img"):
        src = _attr_text(img.get("src"))
        if not src:
            continue
        width = _parse_dimension(img.get("width"))
        height = _parse_dimension(img.get("height"))
        if not _keep_image(width, height):
            continue
        images.append(
            CandidateImage(
                url=src,
                alt=_attr_text(img.get("alt")),
                width=width,
                height=height,
            )
        )
    return images


def _keep_image(width: int | None, height: int | None) -> bool:
    """Keep images whose known dimensions are all >= the minimum.

    Unknown dimensions never cause rejection, so an image with no size
    attributes is kept; a 1x1 tracking pixel is dropped because both of its
    known dimensions fall below the threshold.
    """
    if width is not None and width < MIN_IMAGE_DIMENSION:
        return False
    if height is not None and height < MIN_IMAGE_DIMENSION:
        return False
    return True


def _find_original_url(html: str) -> str | None:
    """Return the href of the first prominent "view on the web" link, if any."""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a"):
        href = _attr_text(anchor.get("href"))
        if not href:
            continue
        text = _collapse_whitespace(anchor.get_text()).lower()
        if any(hint in text for hint in _ORIGINAL_URL_HINTS):
            return href
    return None


def _extract_source(message: EmailMessage) -> str:
    """Use the sender's email address (falling back to display name) as source."""
    name, address = parseaddr(_header_text(message, "From"))
    return address or name


def _extract_received_at(message: EmailMessage) -> datetime | None:
    """Parse the `Date` header into a timezone-aware UTC datetime, or ``None``.

    A `Date` without a timezone is assumed to be UTC. When the header is absent
    or unparseable we return ``None`` (no IMAP internal date is available from a
    `RawEmail`).
    """
    raw_date = _header_text(message, "Date")
    if not raw_date:
        return None
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _header_text(message: EmailMessage, name: str) -> str:
    """Return a header's value as a stripped string (empty when absent)."""
    value = message[name]
    return str(value).strip() if value is not None else ""


def _attr_text(value: object) -> str:
    """Coerce a BeautifulSoup attribute (str, list, or None) to a string."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    return str(value).strip()


def _parse_dimension(value: object) -> int | None:
    """Parse an HTML width/height attribute to an int, or ``None`` if unusable.

    Handles bare integers and a trailing ``px``; percentage or other
    non-integer values are treated as unknown.
    """
    text = _attr_text(value).lower().removesuffix("px").strip()
    try:
        return int(text)
    except ValueError:
        return None


def _collapse_whitespace(text: str) -> str:
    """Collapse all runs of whitespace to single spaces and trim."""
    return " ".join(text.split())
