"""Wiring tests for `app.llm.client.parse_structured`.

These never reach the network or spend money: each test passes a `FakeClient` in
place of the real Groq connection. The fake remembers the request it was given and
replies with a fixed answer. We then check that `parse_structured` asked for the
schema's JSON shape, passed its arguments through, and returned a checked object.
"""

from collections.abc import Iterable
from typing import NoReturn

import pytest
from groq.types.chat import ChatCompletion, ChatCompletionMessageParam
from groq.types.chat.chat_completion import Choice
from groq.types.chat.chat_completion_message import ChatCompletionMessage
from groq.types.chat.completion_create_params import ResponseFormat
from pydantic import BaseModel, ValidationError

from app.llm.client import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    ReasoningEffort,
    parse_structured,
)


class Person(BaseModel):
    name: str
    age: int


def _model_reply(content: str | None) -> ChatCompletion:
    """Build a pretend answer from the model, with `content` as its reply text.

    A `ChatCompletion` is the object Groq returns from a real call, so handing one
    of these to `FakeClient` is how we say "pretend the model replied with this".
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


def _model_reply_without_choices() -> ChatCompletion:
    return ChatCompletion(
        id="test",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[],
    )


class FakeCompletions:
    """Fake `chat.completions`: remembers what it was asked, replies with a fixed
    answer."""

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
    def __init__(self, completions: FakeCompletions) -> None:
        self._completions = completions

    @property
    def completions(self) -> FakeCompletions:
        return self._completions


class FakeClient:
    """A fake Groq connection: the same shape `parse_structured` expects
    (`.chat.completions.create`), but it never touches the network."""

    def __init__(self, response: ChatCompletion) -> None:
        self.completions = FakeCompletions(response)
        self._chat = FakeChat(self.completions)

    @property
    def chat(self) -> FakeChat:
        return self._chat


USER_MESSAGE: list[ChatCompletionMessageParam] = [
    {"role": "user", "content": "Who is Ada Lovelace?"},
]


def test_returns_validated_model_instance() -> None:
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    result = parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert result == Person(name="Ada", age=36)
    assert client.completions.call_count == 1


def test_requests_the_schemas_json_shape() -> None:
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert client.completions.response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "Person",
            "schema": Person.model_json_schema(),
        },
    }


def test_forwards_messages_unchanged() -> None:
    # `messages` is the request we send to the model; `parse_structured` must hand
    # it to Groq exactly as given, without adding or rewriting any of it. The
    # model's answer is not part of this — it comes back separately in the reply.
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert client.completions.messages == USER_MESSAGE


def test_uses_module_default_model_effort_and_max_tokens() -> None:
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert DEFAULT_MODEL == "openai/gpt-oss-120b"
    assert client.completions.model == DEFAULT_MODEL
    assert client.completions.reasoning_effort == DEFAULT_REASONING_EFFORT
    assert client.completions.max_tokens == DEFAULT_MAX_TOKENS


def test_forwards_caller_overrides() -> None:
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(
        messages=USER_MESSAGE,
        schema=Person,
        client=client,
        model="some/other-model",
        reasoning_effort="high",
        max_tokens=99,
    )

    assert client.completions.model == "some/other-model"
    assert client.completions.reasoning_effort == "high"
    assert client.completions.max_tokens == 99


def test_validates_content_and_rejects_bad_shape() -> None:
    # The reply is missing the required `age`, so the `schema.model_validate_json`
    # check inside `parse_structured` raises Pydantic's `ValidationError`. We don't
    # raise it here — it travels up out of `parse_structured` to this test.
    client = FakeClient(_model_reply('{"name": "Ada"}'))

    with pytest.raises(ValidationError):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_raises_when_message_has_no_content() -> None:
    client = FakeClient(_model_reply(None))

    with pytest.raises(ValueError, match="no content"):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_raises_when_response_has_no_choices() -> None:
    client = FakeClient(_model_reply_without_choices())

    with pytest.raises(ValueError, match="no choices"):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_injected_client_never_builds_the_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """When you pass your own client, `parse_structured` must not build the real
    Groq connection, so no real API call can happen. We prove it by making the
    real-connection builder blow up if it is ever called."""

    # Replaces `get_client`, which normally returns a real `Groq`. This stand-in
    # never returns one — it only raises — so its type is `NoReturn`. If
    # `parse_structured` ignores our injected client and calls `get_client`, this
    # fires and fails the test.
    def boom() -> NoReturn:
        raise AssertionError("the real Groq client must never be constructed in tests")

    monkeypatch.setattr("app.llm.client.get_client", boom)
    client = FakeClient(_model_reply('{"name": "Ada", "age": 36}'))

    result = parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert result.name == "Ada"
