"""Shared test doubles for the DeepSeek connection.

`parse_structured` only ever calls `client.chat.completions.create(...)`, so these
fakes reproduce just that path and nothing else. They never touch the network: each
records the request it was handed and returns a fixed reply, so a test can both
control what "the model returned" and check what was sent.

Read the recorded request back through the same path the real code uses, e.g.
`client.chat.completions.call_count` or `.messages`.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any, cast

from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.completion_create_params import ResponseFormat

from app.ingest.parser import CandidateImage, ParsedEmail
from app.llm.client import ReasoningEffort
from app.pipeline.cluster import Topic as ClusterTopic
from app.pipeline.digest import Digest, DigestSource, DigestTopic
from app.pipeline.segment import Story


def model_reply(content: str | None) -> ChatCompletion:
    """Build the model's reply, with `content` as the assistant's answer text.

    A `ChatCompletion` is what the OpenAI-compatible client returns *from* a call
    (the reply, not the request), so handing one to `FakeClient` is how a test
    says "pretend the model answered with this".
    """
    return ChatCompletion(
        id="test",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
    )


def model_reply_without_choices() -> ChatCompletion:
    """Build a reply with no choices, to exercise the empty-reply guard."""
    return ChatCompletion(
        id="test",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[],
    )


def model_reply_truncated(content: str) -> ChatCompletion:
    """Build a reply whose `finish_reason` is `"length"` — it hit `max_tokens`.

    The content is whatever partial text the model managed to emit before the cap.
    `parse_structured` checks `finish_reason` and raises a clear truncation error
    rather than letting pydantic fail with a confusing "EOF while parsing".
    """
    return ChatCompletion(
        id="test",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[
            Choice(
                finish_reason="length",
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
    )


def schema_instruction(messages: list[ChatCompletionMessageParam]) -> str:
    """Return the schema-instruction system message `parse_structured` prepends.

    `parse_structured` always inserts a system message describing the JSON shape
    ahead of the caller's messages. Selecting it by role (rather than by a fixed
    index) keeps these assertions stable if the prepending order ever changes, and
    avoids indexing the union of `ChatCompletionMessageParam` TypedDicts directly.
    """
    systems = [
        m for m in cast(list[dict[str, object]], messages) if m.get("role") == "system"
    ]
    assert len(systems) >= 1
    return str(systems[0]["content"])


class FakeCompletions:
    """Stands in for `chat.completions`: records each request, returns a fixed reply."""

    def __init__(self, response: ChatCompletion) -> None:
        self._response = response
        self.call_count = 0
        self.messages: list[ChatCompletionMessageParam] = []
        self.model: str | None = None
        self.response_format: ResponseFormat | None = None
        self.reasoning_effort: ReasoningEffort | None = None
        self.max_tokens: int | None = None
        self.extra_body: dict[str, Any] | None = None

    def create(
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        model: str,
        response_format: ResponseFormat,
        reasoning_effort: ReasoningEffort,
        max_tokens: int,
        extra_body: dict[str, Any] | None = None,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        self.model = model
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        return self._response


class QueuedCompletions:
    """Returns a different fixed reply for each call, in order.

    Raises ``IndexError`` if a test queues too few responses for the calls made.
    """

    def __init__(self, responses: list[ChatCompletion]) -> None:
        self._responses = responses
        self._next = 0
        self.call_count = 0
        self.messages: list[ChatCompletionMessageParam] = []
        self.model: str | None = None
        self.response_format: ResponseFormat | None = None
        self.reasoning_effort: ReasoningEffort | None = None
        self.max_tokens: int | None = None
        self.extra_body: dict[str, Any] | None = None

    def create(
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        model: str,
        response_format: ResponseFormat,
        reasoning_effort: ReasoningEffort,
        max_tokens: int,
        extra_body: dict[str, Any] | None = None,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        self.model = model
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        response = self._responses[self._next]
        self._next += 1
        return response


class FakeChat:
    """The `.chat` layer: holds the one `completions` the client reaches through."""

    def __init__(self, completions: FakeCompletions | QueuedCompletions) -> None:
        self.completions = completions


class FakeClient:
    """A fake DeepSeek connection shaped like `client.chat.completions.create`."""

    def __init__(self, response: ChatCompletion) -> None:
        self.chat = FakeChat(FakeCompletions(response))


class QueuedFakeClient:
    """A fake that returns a different response for each LLM call.

    Hand it a list of ``ChatCompletion`` replies; the nth call to
    ``client.chat.completions.create(...)`` returns the nth reply. Use this when
    a single pipeline run makes several LLM calls and you want to control what
    each one returns.
    """

    def __init__(self, responses: list[ChatCompletion]) -> None:
        self.chat = FakeChat(QueuedCompletions(responses))


# ---------------------------------------------------------------------------
# domain-object factories — minimal valid instances for tests that need a
# digest, topic, source, or image without running the full pipeline.
# ---------------------------------------------------------------------------


def _image(
    url: str,
    *,
    alt: str = "",
    width: int | None = None,
    height: int | None = None,
) -> CandidateImage:
    """A minimal candidate image, matching the model's own defaults."""
    return CandidateImage(url=url, alt=alt, width=width, height=height)


def _digest_source(
    *,
    source_id: str = "test.eml",
    source: str = "news@test.com",
    subject: str = "Test Subject",
    original_url: str | None = "https://example.com/view/1",
    clean_text: str = "Body text.",
) -> DigestSource:
    """A minimal digest source (the per-topic "view original" link)."""
    return DigestSource(
        id=source_id,
        source=source,
        subject=subject,
        original_url=original_url,
        clean_text=clean_text,
    )


def _digest_topic(
    *,
    label: str = "Test Topic",
    summary: str = "A test summary.",
    sources: list[DigestSource] | None = None,
    image: CandidateImage | None = None,
) -> DigestTopic:
    """A minimal digest topic (one row in the digest card)."""
    return DigestTopic(
        label=label,
        summary=summary,
        sources=sources or [],
        image=image,
    )


def _digest(
    *,
    digest_date: date_type | None = None,
    topics: list[DigestTopic] | None = None,
) -> Digest:
    """A minimal digest for a given date (defaults to 2026-06-15)."""
    return Digest(
        date=digest_date or date_type(2026, 6, 15),
        topics=topics or [],
    )


def _story(
    story_id: str | None = None,
    *,
    source_item_id: str = "news.eml",
    title: str = "Title",
    text: str = "Body.",
) -> Story:
    """A minimal story in a newsletter.  The id defaults to ``{source_item_id}#0``."""
    return Story(
        id=story_id if story_id is not None else f"{source_item_id}#0",
        source_item_id=source_item_id,
        title=title,
        text=text,
    )


def _topic(
    label: str = "Some topic",
    *,
    stories: list[Story] | None = None,
) -> ClusterTopic:
    """A minimal cluster topic (a group of related stories)."""
    return ClusterTopic(label=label, stories=stories or [])


def _parsed_email(
    *,
    item_id: str = "news.eml",
    source: str = "news@example.com",
    subject: str = "Daily digest",
    received_at: datetime | None = None,
    clean_text: str = "Body text.",
    candidate_images: list[CandidateImage] | None = None,
    original_url: str | None = "https://example.com/view/1",
) -> ParsedEmail:
    """A minimal parsed email (as returned by the ingestion parser)."""
    if received_at is None:
        received_at = datetime(2026, 6, 15, tzinfo=UTC)
    return ParsedEmail(
        id=item_id,
        source=source,
        subject=subject,
        received_at=received_at,
        clean_text=clean_text,
        candidate_images=candidate_images or [],
        original_url=original_url,
    )
