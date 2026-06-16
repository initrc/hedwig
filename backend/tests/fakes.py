"""Shared test doubles for the Groq connection.

`parse_structured` only ever calls `client.chat.completions.create(...)`, so these
fakes reproduce just that path and nothing else. They never touch the network: each
records the request it was handed and returns a fixed reply, so a test can both
control what "the model returned" and check what was sent.

Read the recorded request back through the same path the real code uses, e.g.
`client.chat.completions.call_count` or `.messages`.
"""

from collections.abc import Iterable

from groq.types.chat import ChatCompletion, ChatCompletionMessageParam
from groq.types.chat.chat_completion import Choice
from groq.types.chat.chat_completion_message import ChatCompletionMessage
from groq.types.chat.completion_create_params import ResponseFormat

from app.llm.client import ReasoningEffort


def model_reply(content: str | None) -> ChatCompletion:
    """Build the model's reply, with `content` as the assistant's answer text.

    A `ChatCompletion` is what Groq returns *from* a call (the reply, not the
    request), so handing one to `FakeClient` is how a test says "pretend the model
    answered with this".
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

    def create(
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        model: str,
        response_format: ResponseFormat,
        reasoning_effort: ReasoningEffort,
        max_tokens: int,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        self.model = model
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
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

    def create(
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        model: str,
        response_format: ResponseFormat,
        reasoning_effort: ReasoningEffort,
        max_tokens: int,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        self.model = model
        self.response_format = response_format
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        response = self._responses[self._next]
        self._next += 1
        return response


class FakeChat:
    """The `.chat` layer: holds the one `completions` the client reaches through."""

    def __init__(self, completions: FakeCompletions | QueuedCompletions) -> None:
        self.completions = completions


class FakeClient:
    """A fake Groq connection shaped like `client.chat.completions.create`."""

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
