"""The real DeepSeek connection: `OpenAIClient` and the model defaults.

`OpenAIClient` wraps the OpenAI SDK client pointed at DeepSeek and implements
`LLMClient` (the Protocol in `protocol.py`) via `ask()`, inherited from
`_ClientBase`. `OpenAIClient.get()` returns a shared singleton.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from pydantic import BaseModel

from app.llm.protocol import _ClientBase

_logger = logging.getLogger(__name__)

# Switching models is a one-line change here. `deepseek-v4-flash` is DeepSeek's
# fast, low-cost chat model — enough for pulling structured data out of text.
DEFAULT_MODEL = "deepseek-v4-flash"

# DeepSeek's OpenAI-compatible endpoint; the SDK treats it like api.openai.com.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Headroom for any one pipeline stage's JSON reply; too small truncates mid-string.
DEFAULT_MAX_TOKENS = 16384

# "high" is the right level for structured JSON calls; "xhigh" is for agentic
# multi-step contexts and can truncate inside a single reply.
type _ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
_DEFAULT_REASONING_EFFORT: _ReasoningEffort = "high"


class OpenAIClient(_ClientBase):
    """The real DeepSeek connection. Builds the SDK client lazily on first `ask()`."""

    _client: OpenAIClient | None = None

    @classmethod
    def get(cls) -> OpenAIClient:
        """Return the shared singleton, built once on first call."""
        if cls._client is None:
            cls._client = cls()
        return cls._client

    def __init__(self) -> None:
        self._sdk: OpenAI | None = None

    def _get_sdk(self) -> OpenAI:
        if self._sdk is None:
            load_dotenv()
            self._sdk = OpenAI(
                base_url=DEEPSEEK_BASE_URL,
                api_key=os.environ["DEEPSEEK_API_KEY"],
            )
        return self._sdk

    def _complete(
        self,
        *,
        messages: list[ChatCompletionMessageParam],
        schema: type[BaseModel],
        thinking: bool,
    ) -> ChatCompletion:
        extra_body: dict[str, object] = {
            "thinking": {"type": "enabled" if thinking else "disabled"}
        }
        start = time.perf_counter()
        completion = self._get_sdk().chat.completions.create(
            messages=messages,
            model=DEFAULT_MODEL,
            response_format={"type": "json_object"},
            reasoning_effort=_DEFAULT_REASONING_EFFORT,
            max_tokens=DEFAULT_MAX_TOKENS,
            extra_body=extra_body,
        )
        elapsed = time.perf_counter() - start

        usage = completion.usage
        _logger.info(
            "ask schema=%s thinking=%s elapsed=%.1fs tokens=%s",
            schema.__name__,
            "on" if thinking else "off",
            elapsed,
            (
                f"in={usage.prompt_tokens} out={usage.completion_tokens}"
                if usage is not None
                else "unknown"
            ),
        )
        return completion
