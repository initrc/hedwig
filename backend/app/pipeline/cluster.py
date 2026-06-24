"""Group the day's stories into topics, each with a short label.

Segmentation (`segment.py`) turns each email into its separate stories, but a
day's worth of newsletters often covers the same subject from several angles — two
emails both write up one funding round, three mention the same chip launch.
Reading the digest topic by topic is far better than story by story, so this step
asks the language model to group the stories: stories about one subject go in one
topic, unrelated stories stay apart.

The model only ever points at stories by their `id`; our own code resolves those
ids back to the real `Story` objects, and guards against the model naming an id we
never sent or leaving a story out. The policy for a story the model groups with
nothing: it becomes its own one-story topic, so every input story lands in exactly
one topic and nothing is silently lost.
"""

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.llm.protocol import LLMClient
from app.pipeline.segment import Story

# How many characters of each story's text to show the model. The id and title
# carry most of the signal; a short snippet is enough to tell apart two stories
# with similar titles, and keeping it short keeps the whole prompt well within the
# model's context even with a few dozen stories.
_SNIPPET_CHARS = 300


class Topic(BaseModel):
    """One group of related stories, with a short human-readable label.

    `stories` holds the real `Story` objects, already resolved from the ids the
    model returned, so later steps (summarize, image-select) never have to look
    them up again.
    """

    label: str
    stories: list[Story]


class DraftTopic(BaseModel):
    """One group as the language model writes it: a label and the ids it grouped.

    The model points at stories by `id` only — our code turns those ids back into
    `Story` objects. Like `DraftStory` in `segment.py`, this is the model's raw
    reply before our code checks and resolves it.
    """

    label: str
    story_ids: list[str]


class Clustering(BaseModel):
    """The language model's whole reply: every topic it grouped the stories into.

    The topics sit inside this wrapper because the structured-output helper fills
    one object, not a bare list.
    """

    topics: list[DraftTopic]


# Hand-written, and meant to be tweaked as you read real replies: it tells the
# model what counts as "the same topic" and pins it to the ids we sent.
_SYSTEM_PROMPT = (
    "You group a day's news stories into topics. Each story is given with an id, a "
    "title, and a short snippet of its text. Put stories about the same subject or "
    "event into one topic, and keep stories about unrelated subjects in separate "
    "topics. Give each topic a short, plain label of a few words that names the "
    "shared subject. Return groups that reference the stories by their exact ids. "
    "Use each story id at most once, and use only ids that appear in the input — "
    "never invent an id. It is fine for a topic to hold a single story when nothing "
    "else is about that subject."
)


def _story_block(story: Story) -> str:
    """Show one story to the model as three labelled lines: id, title, snippet.

    The snippet collapses the story's own newlines to single spaces so a line
    break inside the text can't be mistaken for the boundary between two stories.
    """
    snippet = " ".join(story.text.split())[:_SNIPPET_CHARS]
    return f"id: {story.id}\ntitle: {story.title}\nsnippet: {snippet}"


def _user_prompt(stories: list[Story]) -> str:
    """Lay every story out as its own block, separated by blank lines."""
    return "\n\n".join(_story_block(story) for story in stories)


def cluster(stories: list[Story], *, client: LLMClient) -> list[Topic]:
    """Group `stories` into topics and return them, every input story placed exactly once.

    An empty list yields no topics, with no model call. The mapping is kept total
    and honest in code, not trusted to the model: a returned id that we never sent
    is dropped, the same story is never placed in two topics, and any story the
    model leaves out of every group becomes its own one-story topic. So every
    returned topic references real input stories, and every input story lands in
    exactly one topic.

    Pass `client` only in tests, to use a fake connection instead of the real DeepSeek
    one.
    """
    if not stories:
        return []

    # Look up table from id back to the real story, so we can resolve the ids the
    # model returns.
    by_id = {story.id: story for story in stories}

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(stories)},
    ]
    clustering = client.ask(
        messages=messages,
        schema=Clustering,
    )

    topics: list[Topic] = []
    placed: set[str] = set()
    for draft in clustering.topics:
        # Keep only ids we actually sent and have not already placed: this drops
        # any hallucinated id and silently ignores a story the model named twice.
        members = [
            by_id[story_id]
            for story_id in draft.story_ids
            if story_id in by_id and story_id not in placed
        ]
        placed.update(story.id for story in members)
        # A topic can end up empty once we strip bad ids; skip it rather than emit
        # a label with no stories under it.
        if members:
            topics.append(Topic(label=draft.label.strip(), stories=members))

    # Any story the model grouped with nothing becomes its own topic, labelled with
    # its title, so the mapping stays total and no story is dropped.
    for story in stories:
        if story.id not in placed:
            topics.append(Topic(label=story.title.strip() or "Other", stories=[story]))

    return topics
