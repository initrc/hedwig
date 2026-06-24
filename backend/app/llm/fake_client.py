"""Pure client stubs for the LLM seam: `FakeClient` (one fixed reply) and
`QueuedFakeClient` (the nth queued reply on the nth call).

Both subclass `_ClientBase` (in `protocol.py`) and implement `_complete()` to
return a pre-built `ChatCompletion`. The shared `ask()` logic — schema-instruction
prepend, guards, validation — is inherited, not duplicated.

Re-exported from `tests/fakes.py` so existing test imports keep working.
"""

from __future__ import annotations

from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from pydantic import BaseModel

from app.llm.protocol import _ClientBase


class FakeClient(_ClientBase):
    """A fake client that returns one fixed reply for every `ask()` call.

    Records the last call's messages on `self.messages` and the total call count
    on `self.call_count`.
    """

    def __init__(self, response: ChatCompletion) -> None:
        self._response = response
        self.call_count = 0
        self.messages: list[ChatCompletionMessageParam] = []

    def _complete(
        self,
        *,
        messages: list[ChatCompletionMessageParam],
        schema: type[BaseModel],
        thinking: bool,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        return self._response


class QueuedFakeClient(_ClientBase):
    """A fake client that returns the nth queued reply on the nth `ask()` call.

    Raises ``IndexError`` if a test queues too few responses for the calls made.
    """

    def __init__(self, responses: list[ChatCompletion]) -> None:
        self._responses = responses
        self._next = 0
        self.call_count = 0
        self.messages: list[ChatCompletionMessageParam] = []

    def _complete(
        self,
        *,
        messages: list[ChatCompletionMessageParam],
        schema: type[BaseModel],
        thinking: bool,
    ) -> ChatCompletion:
        self.call_count += 1
        self.messages = list(messages)
        response = self._responses[self._next]
        self._next += 1
        return response


def model_reply(content: str | None) -> ChatCompletion:
    """Build a reply with `content` as the assistant's answer text."""
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
    """Build a reply whose `finish_reason` is `"length"` — it hit `max_tokens`."""
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
