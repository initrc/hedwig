"""Tests for `FakeClient.ask()` and `QueuedFakeClient.ask()`.

These never reach the network: each test passes a `FakeClient` whose `ask()`
returns a fixed, pre-built reply. The shared guard and validation logic (in
`_ClientBase`, `protocol.py`) runs the same way it does for the real
`OpenAIClient`.
"""

import pytest
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.llm.fake_client import (
    FakeClient,
    QueuedFakeClient,
    model_reply,
    model_reply_truncated,
    model_reply_without_choices,
)
from tests.fakes import make_schema_instruction


class Person(BaseModel):
    name: str
    age: int


USER_MESSAGE: list[ChatCompletionMessageParam] = [
    {"role": "user", "content": "Who is Ada Lovelace?"},
]


def test_returns_validated_model_instance() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    result = client.ask(messages=USER_MESSAGE, schema=Person)

    assert result == Person(name="Ada", age=36)
    assert client.call_count == 1


def test_prepends_schema_instruction_and_preserves_caller_messages() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    client.ask(messages=USER_MESSAGE, schema=Person)

    recorded = client.messages
    assert recorded[1:] == USER_MESSAGE
    instruction = make_schema_instruction(recorded)
    assert "json" in instruction.lower()
    assert "Person" in instruction


def test_validates_content_and_rejects_bad_shape() -> None:
    client = FakeClient(model_reply('{"name": "Ada"}'))

    with pytest.raises(ValidationError):
        client.ask(messages=USER_MESSAGE, schema=Person)


def test_raises_when_message_has_no_content() -> None:
    client = FakeClient(model_reply(None))

    with pytest.raises(ValueError, match="no content"):
        client.ask(messages=USER_MESSAGE, schema=Person)


def test_raises_when_response_has_no_choices() -> None:
    client = FakeClient(model_reply_without_choices())

    with pytest.raises(ValueError, match="no choices"):
        client.ask(messages=USER_MESSAGE, schema=Person)


def test_raises_clear_error_when_reply_truncated_by_max_tokens() -> None:
    client = FakeClient(model_reply_truncated('{"name": "Ada", "age":'))

    with pytest.raises(ValueError, match="truncated"):
        client.ask(messages=USER_MESSAGE, schema=Person)


def test_queued_fake_client_returns_replies_in_order() -> None:
    client = QueuedFakeClient(
        [
            model_reply('{"name": "Ada", "age": 36}'),
            model_reply('{"name": "Bob", "age": 24}'),
        ]
    )

    first = client.ask(messages=USER_MESSAGE, schema=Person)
    second = client.ask(messages=USER_MESSAGE, schema=Person)

    assert first == Person(name="Ada", age=36)
    assert second == Person(name="Bob", age=24)
    assert client.call_count == 2
