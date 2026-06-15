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


class FakeChat:
    """The `.chat` layer: holds the one `completions` the client reaches through."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    """A fake Groq connection shaped like `client.chat.completions.create`."""

    def __init__(self, response: ChatCompletion) -> None:
        self.chat = FakeChat(FakeCompletions(response))
