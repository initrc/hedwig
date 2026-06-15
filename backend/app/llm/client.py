"""Talk to the Groq language model and get back a checked Python object.

This file gives the rest of the app two things:

- `get_client()` — one ready-to-use Groq connection, shared across the app.
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
  uses the shared Groq connection; a test can pass in a fake connection that
  returns a fixed reply, so tests never reach the network or cost money.
"""

from collections.abc import Iterable
from functools import lru_cache
from typing import Literal, Protocol

from dotenv import load_dotenv
from groq import Groq
from groq.types.chat import ChatCompletion, ChatCompletionMessageParam
from groq.types.chat.completion_create_params import ResponseFormat
from pydantic import BaseModel

# How hard the model should "think" before it answers. gpt-oss-120b is a
# reasoning model, so a higher level gives a more careful answer but is slower and
# costs more. Groq also allows "none" and "default", but we only ever turn
# reasoning up or down, so we offer just these three. This is a plain set of
# allowed strings (a Literal), not an Enum, because that is exactly what the Groq
# library wants, so the chosen value can be passed straight through to it.
type ReasoningEffort = Literal["low", "medium", "high"]

# The model name lives here and nowhere else, so switching models is a one-line
# change. This is a strong, low-cost open model that Groq runs quickly — more than
# enough for pulling structured data out of text, which does not need a top model.
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Start at the cheapest, fastest level; a caller can raise it for a request that
# needs more careful thinking.
DEFAULT_REASONING_EFFORT: ReasoningEffort = "low"

# A cap on how long the model's reply may be (counted in tokens, which are roughly
# word-sized chunks of text). The replies here are small, so a few thousand is
# plenty; a caller can raise it when they need more room.
DEFAULT_MAX_TOKENS = 4096


# The three small classes below describe the shape of the Groq connection, but
# only the part that `parse_structured` (further down) actually uses: the one call
# it ever makes is `client.chat.completions.create(...)`. So that is all we list.
#
# Why describe the shape instead of just using the real Groq type? Because then a
# test can hand `parse_structured` a fake connection that has the same `create`
# method. `Protocol` is Python's way of saying "any object with this shape is
# accepted here" — the fake fits, and the real Groq connection fits too, without
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
    """The Groq connection as `parse_structured` sees it: a `.chat` that leads to
    the `create` call, and nothing else."""

    @property
    def chat(self) -> _Chat: ...


@lru_cache(maxsize=1)
def get_client() -> Groq:
    """Build the shared Groq connection the first time it is needed, then reuse it.

    `load_dotenv()` reads the `.env` file so the `GROQ_API_KEY` setting is
    available. We do it here because this code can run on its own, not only inside
    the web app (which reads `.env` in `main.py`), so we cannot assume the key was
    loaded already. `Groq()` then picks up `GROQ_API_KEY` from the environment by
    itself — we never write the key in code. `@lru_cache(maxsize=1)` makes Python
    build the connection once and hand back that same one on every later call.
    """
    load_dotenv()
    return Groq()


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
    model describing the answer you want. This function asks Groq to reply as JSON
    shaped like `schema`, checks that reply against `schema`, and returns the
    filled-in object. If the reply does not match `schema`, the check raises an
    error rather than returning bad data, so a call that succeeds always gives you
    a valid object. Only the model's final answer is returned; its private
    "thinking" text is dropped.

    Pass `client` only in tests, to use a fake connection instead of the real one.
    """
    active_client = client if client is not None else get_client()

    # Tell Groq to answer as JSON shaped like `schema`. `model_json_schema()` turns
    # the Pydantic model into a JSON description of its fields that Groq can follow.
    response_format: ResponseFormat = {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
        },
    }

    completion = active_client.chat.completions.create(
        messages=messages,
        model=model,
        response_format=response_format,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )

    # The model can return several alternative answers (its "choices") if you ask
    # for more than one; we only ever ask for one, so we read the first and only
    # answer. Guard the two ways a reply can still come back empty before reading
    # its text, so a missing answer raises a clear error instead of crashing.
    if not completion.choices:
        raise ValueError("The model returned no choices")
    content = completion.choices[0].message.content
    if content is None:
        raise ValueError("The model's reply had no content")

    # Check the JSON text against `schema` and return the filled-in object.
    return schema.model_validate_json(content)
