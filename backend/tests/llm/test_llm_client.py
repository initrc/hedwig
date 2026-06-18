"""Wiring tests for `app.llm.client.parse_structured`.

These never reach the network or spend money: each test passes a `FakeClient`
(from `tests.fakes`) in place of the real DeepSeek connection. The fake remembers
the request it was given and replies with a fixed answer. We then check that
`parse_structured` asked for the schema's JSON shape, passed its arguments through,
and returned a checked object.
"""

from typing import NoReturn

import pytest
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.llm.client import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    parse_structured,
)
from tests.fakes import (
    FakeClient,
    model_reply,
    model_reply_truncated,
    model_reply_without_choices,
    schema_instruction,
)


class Person(BaseModel):
    name: str
    age: int


USER_MESSAGE: list[ChatCompletionMessageParam] = [
    {"role": "user", "content": "Who is Ada Lovelace?"},
]


def test_returns_validated_model_instance() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    result = parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert result == Person(name="Ada", age=36)
    assert client.chat.completions.call_count == 1


def test_requests_loose_json_object_mode() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    # DeepSeek only supports loose JSON mode, so the structured shape lives in the
    # prompt (a prepended system message) rather than in an API-enforced schema.
    assert client.chat.completions.response_format == {"type": "json_object"}


def test_prepends_schema_instruction_and_preserves_caller_messages() -> None:
    # `parse_structured` must hand the caller's messages to the model unchanged, and
    # prepend a system message describing the JSON shape (DeepSeek's json_object
    # mode needs the word "json" and a shape description in the prompt).
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    recorded = client.chat.completions.messages
    # The caller's messages follow the injected schema instruction, untouched.
    assert recorded[1:] == USER_MESSAGE
    instruction = schema_instruction(recorded)
    assert "json" in instruction.lower()
    assert "Person" in instruction


def test_uses_module_default_model_effort_and_max_tokens() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert DEFAULT_MODEL == "deepseek-v4-flash"
    assert client.chat.completions.model == DEFAULT_MODEL
    assert client.chat.completions.reasoning_effort == DEFAULT_REASONING_EFFORT
    assert client.chat.completions.max_tokens == DEFAULT_MAX_TOKENS


def test_forwards_caller_overrides() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(
        messages=USER_MESSAGE,
        schema=Person,
        client=client,
        model="some/other-model",
        reasoning_effort="xhigh",
        max_tokens=99,
    )

    assert client.chat.completions.model == "some/other-model"
    assert client.chat.completions.reasoning_effort == "xhigh"
    assert client.chat.completions.max_tokens == 99


def test_validates_content_and_rejects_bad_shape() -> None:
    # The reply is missing the required `age`, so the `schema.model_validate_json`
    # check inside `parse_structured` raises Pydantic's `ValidationError`. We don't
    # raise it here — it travels up out of `parse_structured` to this test.
    client = FakeClient(model_reply('{"name": "Ada"}'))

    with pytest.raises(ValidationError):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_raises_when_message_has_no_content() -> None:
    client = FakeClient(model_reply(None))

    with pytest.raises(ValueError, match="no content"):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_raises_when_response_has_no_choices() -> None:
    client = FakeClient(model_reply_without_choices())

    with pytest.raises(ValueError, match="no choices"):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_raises_clear_error_when_reply_truncated_by_max_tokens() -> None:
    # `finish_reason="length"` means the model hit `max_tokens` before finishing
    # the JSON. Parsing it would fail with a confusing "EOF while parsing"; instead
    # `parse_structured` surfaces the real cause so a caller knows to raise max_tokens.
    client = FakeClient(model_reply_truncated('{"name": "Ada", "age":'))

    with pytest.raises(ValueError, match="truncated at max_tokens"):
        parse_structured(messages=USER_MESSAGE, schema=Person, client=client)


def test_default_passes_thinking_enabled() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert client.chat.completions.extra_body == {"thinking": {"type": "enabled"}}


def test_thinking_false_passes_thinking_disabled() -> None:
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    parse_structured(messages=USER_MESSAGE, schema=Person, client=client, thinking=False)

    assert client.chat.completions.extra_body == {"thinking": {"type": "disabled"}}


def test_injected_client_never_builds_the_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """When you pass your own client, `parse_structured` must not build the real
    DeepSeek connection, so no real API call can happen. We prove it by making the
    real-connection builder blow up if it is ever called."""

    # Replaces `get_client`, which normally returns a real DeepSeek client. This
    # stand-in never returns one — it only raises — so its type is `NoReturn`. If
    # `parse_structured` ignores our injected client and calls `get_client`, this
    # fires and fails the test.
    def boom() -> NoReturn:
        raise AssertionError("the real DeepSeek client must never be constructed in tests")

    monkeypatch.setattr("app.llm.client.get_client", boom)
    client = FakeClient(model_reply('{"name": "Ada", "age": 36}'))

    result = parse_structured(messages=USER_MESSAGE, schema=Person, client=client)

    assert result.name == "Ada"
