"""Talk to the DeepSeek language model and get back a checked Python object.

This file gives the rest of the app two things:

- `get_client()` — one ready-to-use DeepSeek connection (via its OpenAI-compatible
  endpoint), shared across the app.
- `parse_structured(...)` — the main function callers use. You give it your chat
  messages and a Pydantic model that describes the answer you want. It sends the
  messages to the model, reads the model's JSON reply, checks that reply against
  your Pydantic model, and returns the filled-in object. If the reply does not
  fit the model, it raises an error instead of handing back half-filled data.

So callers get a real, checked Python object back, not raw JSON they have to pick
apart by hand.

Good to know:
- The model name lives in one place (`DEFAULT_MODEL`), so changing models is a
  one-line edit.
- `parse_structured` takes an optional `client`. Normal code leaves it out and
  uses the shared DeepSeek connection; a test can pass in a fake connection that
  returns a fixed reply, so tests never reach the network or cost money.
"""

import json
import os
from collections.abc import Iterable
from functools import lru_cache
from typing import Literal, Protocol

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.completion_create_params import ResponseFormat
from pydantic import BaseModel

# The model name lives here and nowhere else, so switching models is a one-line
# change. `deepseek-v4-flash` is DeepSeek's fast, low-cost chat model — more than
# enough for pulling structured data out of text.
DEFAULT_MODEL = "deepseek-v4-flash"

# The base URL for DeepSeek's OpenAI-compatible chat-completions endpoint. The
# OpenAI SDK talks to it exactly like it would api.openai.com; only the URL and
# API key differ.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# How hard the model should "think" before it answers. DeepSeek's thinking mode
# is on by default; `reasoning_effort` controls how deep the chain-of-thought
# goes before the final answer. DeepSeek maps "low" and "medium" to "high", and
# "xhigh" to "max", so the two values that actually change behaviour are "high"
# (the default for regular requests) and "xhigh" (DeepSeek's top tier). The
# values here match the OpenAI SDK's own `ReasoningEffort` literal so the real
# client structurally satisfies the `LLMClient` Protocol mypy checks against.
type ReasoningEffort = Literal["low", "medium", "high", "xhigh"]

# Start at DeepSeek's regular-request default. DeepSeek's "high" is the right
# level for the structured JSON calls in this app; the deeper "xhigh"/"max" tier
# is intended for agentic multi-step contexts (per DeepSeek's thinking-mode docs)
# and produces chain-of-thought long enough to truncate inside a single reply.
# The parameter stays available on `parse_structured` for any future call that
# genuinely needs more reasoning.
DEFAULT_REASONING_EFFORT: ReasoningEffort = "high"

# A cap on how long the model's reply may be (counted in tokens, which are roughly
# word-sized chunks of text). DeepSeek-v4-flash allows up to 384K output tokens; we
# pick a default with comfortable headroom for any single pipeline stage's JSON
# reply (segmentation of a long newsletter is the largest — its stories' full text
# can run several thousand tokens). Too small a cap truncates the JSON mid-string,
# which then fails to parse. Callers can still pass a larger `max_tokens` if needed.
DEFAULT_MAX_TOKENS = 16384


# The three small classes below describe the shape of the DeepSeek connection, but
# only the part that `parse_structured` (further down) actually uses: the one call
# it ever makes is `client.chat.completions.create(...)`. So that is all we list.
#
# Why describe the shape instead of just using the real OpenAI type? Because then a
# test can hand `parse_structured` a fake connection that has the same `create`
# method. `Protocol` is Python's way of saying "any object with this shape is
# accepted here" — the fake fits, and the real DeepSeek connection fits too, without
# either one having to declare it.


class _Completions(Protocol):
    """Has `create`, the method `parse_structured` calls to ask the model."""

    def create(
        self,
        *,
        messages: Iterable[ChatCompletionMessageParam],
        model: str,
        response_format: ResponseFormat,
        reasoning_effort: ReasoningEffort,
        max_tokens: int,
    ) -> ChatCompletion: ...


class _Chat(Protocol):
    """Has `completions`, matching the real client's `client.chat.completions`."""

    @property
    def completions(self) -> _Completions: ...


class LLMClient(Protocol):
    """The DeepSeek connection as `parse_structured` sees it: a `.chat` that leads to
    the `create` call, and nothing else."""

    @property
    def chat(self) -> _Chat: ...


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Build the shared DeepSeek connection the first time it is needed, then reuse it.

    `load_dotenv()` reads the `.env` file so the `DEEPSEEK_API_KEY` setting is
    available. We do it here because this code can run on its own, not only inside
    the web app (which reads `.env` in `main.py`), so we cannot assume the key was
    loaded already. The `api_key` is passed explicitly: the OpenAI SDK defaults to
    `OPENAI_API_KEY`, which here is the OpenAI embedding key — passing it to
    DeepSeek would send the wrong credential. `@lru_cache(maxsize=1)` makes Python
    build the connection once and hand back that same one on every later call.
    """
    load_dotenv()
    return OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=os.environ["DEEPSEEK_API_KEY"])


def parse_structured[SchemaT: BaseModel](
    *,
    messages: Iterable[ChatCompletionMessageParam],
    schema: type[SchemaT],
    client: LLMClient | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> SchemaT:
    """Ask the model a question and return the answer as a checked `schema` object.

    `messages` is your chat (the system and user messages). `schema` is a Pydantic
    model describing the answer you want. This function asks DeepSeek to reply as
    JSON shaped like `schema`, checks that reply against `schema`, and returns the
    filled-in object. If the reply does not match `schema`, the check raises an
    error rather than returning bad data, so a call that succeeds always gives you
    a valid object. Only the model's final answer is returned.

    DeepSeek's API only offers loose JSON mode (`response_format={'type':
    'json_object'}`), not schema-enforced JSON, so the schema is also written into
    a leading system message that tells the model exactly what shape to produce.
    The reply is still validated against `schema` afterwards, so a bad shape can
    never slip through.

    Pass `client` only in tests, to use a fake connection instead of the real one.
    """
    active_client = client if client is not None else get_client()

    # DeepSeek's json_object mode requires the word "json" in the prompt and a
    # description of the desired shape. We prepend a system message carrying both,
    # so the caller's own messages stay untouched and the model is pinned to one
    # JSON object matching the schema.
    schema_instruction = (
        f"Reply with a single JSON object that matches the \"{schema.__name__}\" "
        f"JSON schema exactly. Output only that JSON object, with no other text.\n\n"
        f"JSON schema:\n{json.dumps(schema.model_json_schema())}"
    )
    augmented_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": schema_instruction},
        *messages,
    ]

    completion = active_client.chat.completions.create(
        messages=augmented_messages,
        model=model,
        response_format={"type": "json_object"},
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )

    # The model can return several alternative answers (its "choices") if you ask
    # for more than one; we only ever ask for one, so we read the first and only
    # answer. Guard the two ways a reply can still come back empty before reading
    # its text, so a missing answer raises a clear error instead of crashing.
    if not completion.choices:
        raise ValueError("The model returned no choices")
    choice = completion.choices[0]
    # `finish_reason == "length"` means the reply hit `max_tokens` before finishing.
    # For a JSON reply that guarantees truncation mid-string, so parsing would fail
    # with a confusing "EOF while parsing" error. Surface the real cause instead.
    if choice.finish_reason == "length":
        raise ValueError(
            f"The model's reply was truncated at max_tokens={max_tokens} before "
            "the JSON finished. Raise max_tokens for this call."
        )
    content = choice.message.content
    if not content:
        raise ValueError("The model's reply had no content")

    # Check the JSON text against `schema` and return the filled-in object.
    return schema.model_validate_json(content)
