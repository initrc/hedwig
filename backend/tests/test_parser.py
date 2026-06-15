from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from app.ingest.parser import Item, parse
from app.ingest.source import LocalEmlSource, RawEmail

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def make_raw(
    *,
    html: str | None = None,
    plain: str | None = None,
    subject: str = "Weekly digest",
    sender: str = "News <news@example.com>",
    date: str | None = "Tue, 09 Jun 2026 23:34:48 +0000",
    source_id: str = "fixture.eml",
) -> RawEmail:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    if date is not None:
        message["Date"] = date
    if plain is not None:
        message.set_content(plain)
    if html is not None:
        if plain is not None:
            message.add_alternative(html, subtype="html")
        else:
            message.set_content(html, subtype="html")
    return RawEmail(source_id=source_id, message=message)


def test_html_is_stripped_to_collapsed_text() -> None:
    html = """
    <html><body>
      <h1>Big   News</h1>
      <p>Hello   <b>world</b>,
         this is a <a href="#">test</a>.</p>
      <script>ignore_me()</script>
    </body></html>
    """
    item = parse(make_raw(html=html))
    assert "<" not in item.clean_text
    assert "ignore_me" not in item.clean_text
    assert "Big News" in item.clean_text
    assert "Hello world , this is a test ." in item.clean_text


def test_image_filtering_threshold() -> None:
    html = """
    <img src="https://e/pixel.gif" width="1" height="1" alt="">
    <img src="https://e/icon.png" width="60" height="60" alt="icon">
    <img src="https://e/hero.png" width="600" height="400" alt="Hero">
    <img src="https://e/wide.png" width="560" alt="Wide">
    <img src="https://e/unknown.png" alt="">
    <img src="https://e/skinny.png" width="800" height="40" alt="bar">
    """
    item = parse(make_raw(html=html))
    urls = [img.url for img in item.candidate_images]
    assert urls == [
        "https://e/hero.png",
        "https://e/wide.png",
        "https://e/unknown.png",
    ]


def test_image_without_src_is_skipped_and_alt_defaults_to_empty() -> None:
    html = '<img width="600" height="400"><img src="https://e/hero.png" width="600" height="400">'
    item = parse(make_raw(html=html))
    assert len(item.candidate_images) == 1
    assert item.candidate_images[0].alt == ""


def test_px_suffix_and_percentage_dimensions() -> None:
    html = (
        '<img src="https://e/px.png" width="600px" height="400px" alt="px">'
        '<img src="https://e/pct.png" width="100%" alt="pct">'
    )
    item = parse(make_raw(html=html))
    by_url = {img.url: img for img in item.candidate_images}
    assert by_url["https://e/px.png"].width == 600
    assert by_url["https://e/px.png"].height == 400
    # A percentage width is unusable, so it is treated as unknown and kept.
    assert by_url["https://e/pct.png"].width is None


def test_original_url_extracted_from_view_in_browser_link() -> None:
    html = """
    <a href="https://news.example.com/web/123">View in browser</a>
    <a href="https://news.example.com/article">Read the full story</a>
    """
    item = parse(make_raw(html=html))
    assert item.original_url == "https://news.example.com/web/123"


def test_original_url_is_none_when_absent() -> None:
    item = parse(make_raw(html="<p>No web link here.</p>"))
    assert item.original_url is None


def test_plain_text_only_message_skips_html_extraction() -> None:
    item = parse(make_raw(plain="Just   plain\n\ntext   here."))
    assert item.clean_text == "Just plain text here."
    assert item.candidate_images == []
    assert item.original_url is None


def test_missing_date_yields_none_received_at() -> None:
    item = parse(make_raw(html="<p>hi</p>", date=None))
    assert item.received_at is None


def test_received_at_is_utc_aware() -> None:
    item = parse(make_raw(html="<p>hi</p>", date="Tue, 09 Jun 2026 23:34:48 +0200"))
    assert item.received_at == datetime(2026, 6, 9, 21, 34, 48, tzinfo=UTC)
    assert item.received_at.tzinfo is not None


def test_naive_date_is_assumed_utc() -> None:
    item = parse(make_raw(html="<p>hi</p>", date="Tue, 09 Jun 2026 23:34:48 -0000"))
    assert item.received_at == datetime(2026, 6, 9, 23, 34, 48, tzinfo=UTC)


def test_source_is_sender_address() -> None:
    item = parse(make_raw(html="<p>hi</p>", sender="AlphaSignal <news@alphasignal.ai>"))
    assert item.source == "news@alphasignal.ai"


def test_roundtrip_over_committed_samples() -> None:
    items = [parse(raw) for raw in LocalEmlSource(SAMPLES_DIR).fetch()]
    assert items, "expected committed samples/*.eml to yield items"
    for item in items:
        # Re-validate to prove each item matches the schema end to end.
        Item.model_validate(item.model_dump())
        assert item.id.endswith(".eml")
        assert item.source
        assert item.subject
        assert item.clean_text
        assert item.received_at is not None
        assert item.received_at.tzinfo is not None
        for img in item.candidate_images:
            assert img.url
            if img.width is not None:
                assert img.width >= 100
            if img.height is not None:
                assert img.height >= 100
