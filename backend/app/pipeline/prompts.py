"""Versioned summarization prompts, stored as named artifacts.

The summarization prompt is the build plan's core prompt-engineering surface
(Day 2). Editing it blind — "I changed it and it looks fine" — is what this
registry replaces. Prompts live here as named, versioned strings, and
`summarize_topic` looks one up by name, so a caller can opt into a different
version (e.g. by the prompt-comparison eval) without touching the production
default.

Versions
--------

- ``v1`` is the original summarization prompt, verbatim — the one the production
  pipeline has always used. It is the default, so nothing about the production
  pipeline changes unless a caller opts in.
- ``v2`` is a deliberate variant, not necessarily better. It asks for a tighter
  summary (a hard sentence/word budget) and to ignore boilerplate, sponsor, and
  unsubscribe text. The point is to demonstrate the regression mechanism, not to
  ship an improved prompt. Record what v2 changed and the measured delta in the
  task findings once a live run is done.

Lookups go through `get_summarize_prompt`, which raises `KeyError` for an
unknown version so a typo fails loudly instead of silently falling back to v1.
"""

from __future__ import annotations

# The production default. Kept as a name, not a literal, so a caller reading
# `summarize_topic`'s signature sees "v1" rather than a magic string.
DEFAULT_PROMPT_VERSION = "v1"

SUMMARIZE_PROMPTS: dict[str, str] = {
    "v1": (
        "You write up one topic from a day's newsletters. You are given the topic's "
        "stories, each tagged with the id of the source newsletter it came from. Write "
        "a short summary that combines the stories into one account and stays true to "
        "them, adding nothing they do not say. Cite your sources: return the ids of the "
        "source newsletters your summary uses, using only ids that appear in the input "
        "and never inventing one."
    ),
    "v2": (
        "You write up one topic from a day's newsletters. You are given the topic's "
        "stories, each tagged with the id of the source newsletter it came from. Write "
        "a tight summary of two to three sentences (roughly 60 words at most) that "
        "combines the stories into one account and stays true to them, adding nothing "
        "they do not say. Cut every word that does not carry information. Ignore "
        "boilerplate, sponsor messages, and unsubscribe text — they are not part of the "
        "story. Cite your sources: return the ids of the source newsletters your "
        "summary uses, using only ids that appear in the input and never inventing one."
    ),
}


def get_summarize_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    """Return the summarization prompt for *version*.

    Raises `KeyError` for an unknown version so a typo fails loudly rather than
    silently falling back to the default.
    """
    return SUMMARIZE_PROMPTS[version]


__all__ = [
    "DEFAULT_PROMPT_VERSION",
    "SUMMARIZE_PROMPTS",
    "get_summarize_prompt",
]
