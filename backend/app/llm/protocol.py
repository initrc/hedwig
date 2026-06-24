"""The LLM seam: the `LLMClient` Protocol and a shared base for implementations.

`LLMClient` is the interface — any object with an `ask()` method that takes chat
messages and a Pydantic schema and returns a validated object of that schema.
`_ClientBase` is the shared implementation: `ask()` prepends the schema
instruction, calls `_complete()` for the raw reply, then guards and validates.
`OpenAIClient` (in `client.py`) and `FakeClient` (in `fake_client.py`) subclass
it and supply `_complete()`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol

from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from pydantic import BaseModel


class LLMClient(Protocol):
    """Anything with an `ask()` method that returns a schema-validated object."""

    def ask[SchemaT: BaseModel](
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        schema: type[SchemaT],
        thinking: bool = True,
    ) -> SchemaT: ...


class _ClientBase:
    """Shared `ask()` logic for `LLMClient` implementations.

    `ask()` prepends a schema-instruction system message, calls `_complete()`
    for the raw `ChatCompletion`, then guards the reply (no choices, truncated,
    no content) and validates it against `schema`. Subclasses implement
    `_complete()` — `OpenAIClient` calls the real model, `FakeClient` returns
    a pre-built reply.
    """

    def ask[SchemaT: BaseModel](
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        schema: type[SchemaT],
        thinking: bool = True,
    ) -> SchemaT:
        schema_instruction = (
            f"Reply with a single JSON object that matches the \"{schema.__name__}\" "
            f"JSON schema exactly. Output only that JSON object, with no other text.\n\n"
            f"JSON schema:\n{json.dumps(schema.model_json_schema())}"
        )
        augmented: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": schema_instruction},
            *messages,
        ]

        completion = self._complete(messages=augmented, schema=schema, thinking=thinking)

        if not completion.choices:
            raise ValueError("The model returned no choices")
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise ValueError(
                "The model's reply was truncated at the max_tokens cap. "
                "Raise max_tokens for this call."
            )
        content = choice.message.content
        if not content:
            raise ValueError("The model's reply had no content")

        return schema.model_validate_json(content)

    def _complete(
        self,
        *,
        messages: list[ChatCompletionMessageParam],
        schema: type[BaseModel],
        thinking: bool,
    ) -> ChatCompletion:
        raise NotImplementedError
