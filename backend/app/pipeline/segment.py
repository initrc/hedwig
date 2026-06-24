"""Split one newsletter email into the separate stories it contains.

Parsing makes one `ParsedEmail` per email, but a newsletter usually bundles many
unrelated stories under one subject line — a product launch, a market note, a
research paper. Grouping whole emails by topic later would be too coarse, so this
step asks the language model to break each email into its stories first.

The language model writes only each story's title and text; our own code adds the
ids, which it would not get right.
"""

from collections.abc import Iterable

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.ingest.parser import ParsedEmail
from app.llm.protocol import LLMClient


class Story(BaseModel):
    """One story split out of a newsletter email, ready to be clustered.

    `source_item_id` is the parent `ParsedEmail.id`, kept so a later step can find that
    email's images and links again.
    """

    id: str
    source_item_id: str
    title: str
    text: str


class DraftStory(BaseModel):
    """A story as the language model writes it: a title and text, with no id yet.

    Our code adds the ids when it turns each draft into a finished `Story`.
    """

    title: str
    text: str


class Segmentation(BaseModel):
    """The language model's whole reply: every story it found in one email.

    The drafts sit inside this wrapper because the structured-output helper fills
    one object, not a bare list.
    """

    stories: list[DraftStory]


# Hand-written, and meant to be tweaked as you read real replies: it tells the
# model what a "story" is and what to leave out.
_SYSTEM_PROMPT = (
    "You split a newsletter email into the separate stories it contains. "
    "A newsletter usually bundles several unrelated stories — a product launch, a "
    "market note, a research paper — under one subject line. Return each distinct "
    "story on its own, each with a short title and that story's own text taken from "
    "the email. Do not merge unrelated stories together, and do not invent stories "
    "that are not in the email. Leave out boilerplate such as greetings, sign-offs, "
    "adverts, and 'view in browser' links. If the email really is about a single "
    "story, return just that one."
)


def _user_prompt(item: ParsedEmail) -> str:
    """Lay the email out the way email itself does: subject line, blank line, body."""
    return f"Subject: {item.subject}\n\n{item.clean_text}"


def segment(item: ParsedEmail, *, client: LLMClient) -> list[Story]:
    """Split one email into its stories.

    Empty or whitespace-only text yields no stories, with no model call. Pass
    `client` only in tests, to use a fake connection instead of the real DeepSeek one.
    """
    if not item.clean_text.strip():
        return []

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(item)},
    ]
    # Keep the helper's default reply size: each story's text is a slice of this one
    # email, so all the stories together never outrun it. Thinking is off: splitting
    # a newsletter into titled chunks is extraction, not reasoning, and skipping the
    # chain-of-thought keeps this per-email call fast (it runs once per email).
    segmentation = client.ask(
        messages=messages, schema=Segmentation, thinking=False
    )

    # Number the drafts from 0 to build ids, so the first story of email "x.eml"
    # gets id "x.eml#0".
    return [
        Story(
            id=f"{item.id}#{index}",
            source_item_id=item.id,
            title=draft.title.strip(),
            text=draft.text.strip(),
        )
        for index, draft in enumerate(segmentation.stories)
    ]


def segment_items(items: Iterable[ParsedEmail], *, client: LLMClient) -> list[Story]:
    """Split many emails and return all their stories in one flat list."""
    stories: list[Story] = []
    for item in items:
        stories.extend(segment(item, client=client))
    return stories
