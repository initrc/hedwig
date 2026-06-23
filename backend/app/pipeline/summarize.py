"""Write up one topic into a short summary with checked citations.

Clustering (`cluster.py`) groups the day's stories into topics. This step turns
each topic into a short summary plus the list of newsletters it uses.

Citations are checked, not trusted. We give the model a fixed id for each story's
source newsletter (`Story.source_item_id`, which is the `ParsedEmail.id` it came
from) and ask it to cite by that id. Then our code keeps only ids we really sent
and drops any the model made up, so every citation points to a real source.
"""

from collections.abc import Iterable

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.llm.client import LLMClient, parse_structured
from app.pipeline.cluster import Topic
from app.pipeline.prompts import DEFAULT_PROMPT_VERSION, get_summarize_prompt
from app.pipeline.segment import Story


class Source(BaseModel):
    """One citation: the newsletter a claim in the summary came from.

    We cite by `source_item_id` — the `ParsedEmail.id` the story came from. Kept as
    a small model, not a bare string, so later steps can read the field by name.
    """

    source_item_id: str


class TopicSummary(BaseModel):
    """The finished topic: its label, summary, and citations.

    `label` comes from the `Topic` (set by clustering), copied here so this object
    stands alone and later steps need not keep the original `Topic`.
    """

    label: str
    summary: str
    sources: list[Source]


class DraftSummary(BaseModel):
    """The model's reply: the summary text and the source ids it cites.

    No `label`: clustering already set the topic's label, so `summarize_topic`
    copies `Topic.label` across instead of asking the model for a new one. This is
    the raw reply, before our code checks the ids (like `DraftStory`/`DraftTopic`).
    """

    summary: str
    source_ids: list[str]


# The summarization prompt, kept as a versioned artifact in `prompts.py` so it
# can be swapped (e.g. by the prompt-comparison eval) without editing this file.
# Kept here as a name as well so `evals.injection` can still import the literal
# text it checks for leakage; it always equals the v1 prompt.
_SYSTEM_PROMPT = get_summarize_prompt(DEFAULT_PROMPT_VERSION)


def _story_block(story: Story) -> str:
    """Show one story to the model: its source id, title, and full text.

    The text's own line breaks are collapsed to spaces so a break inside a story is
    not read as the gap between two stories. The full text is shown, not a snippet,
    because the summary has to stay true to all of it.
    """
    text = " ".join(story.text.split())
    return f"source: {story.source_item_id}\ntitle: {story.title}\ntext: {text}"


def _user_prompt(topic: Topic) -> str:
    """Lay out the topic label, then each story as its own block."""
    blocks = "\n\n".join(_story_block(story) for story in topic.stories)
    return f"Topic: {topic.label}\n\n{blocks}"


def _resolve_sources(source_ids: Iterable[str], valid: set[str]) -> list[Source]:
    """Keep only cited ids we really sent, each once, in first-cited order.

    Drops an id we never sent (the model made it up) and a repeat of one we did.
    """
    sources: list[Source] = []
    seen: set[str] = set()
    for source_id in source_ids:
        if source_id in valid and source_id not in seen:
            seen.add(source_id)
            sources.append(Source(source_item_id=source_id))
    return sources


def summarize_topic(
    topic: Topic,
    *,
    client: LLMClient | None = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> TopicSummary:
    """Summarize one `topic`, keeping only citations that point to its sources.

    The citations are checked in code: `sources` can only name a newsletter that
    fed this topic (found through `Story.source_item_id`); anything else is dropped.

    `prompt_version` selects the summarization prompt from the registry in
    `prompts.py`. It defaults to v1 — the prompt the production pipeline has
    always used — so callers that omit it see no change. Pass another version
    (e.g. "v2") to run a regression comparison without forking the pipeline.

    Pass `client` only in tests, to use a fake connection instead of the real one.
    """
    # The ids we accept as citations: the source newsletter behind each story. One
    # newsletter can back several stories, so this is a set.
    valid = {story.source_item_id for story in topic.stories}

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": get_summarize_prompt(prompt_version)},
        {"role": "user", "content": _user_prompt(topic)},
    ]
    draft = parse_structured(
        messages=messages,
        schema=DraftSummary,
        client=client,
    )

    return TopicSummary(
        label=topic.label,
        summary=draft.summary.strip(),
        sources=_resolve_sources(draft.source_ids, valid),
    )


def summarize_topics(
    topics: Iterable[Topic],
    *,
    client: LLMClient | None = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> list[TopicSummary]:
    """Summarize many topics, in the same order."""
    return [
        summarize_topic(topic, client=client, prompt_version=prompt_version)
        for topic in topics
    ]
