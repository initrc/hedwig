"""Pick the one image that best illustrates each topic, or none at all.

A topic is built from several stories, and those stories come from one or more
newsletter emails. Each of those emails already carries a list of candidate
images that parsing gathered and rough-filtered (it dropped tiny logos and
tracking pixels by size). But "big enough to keep" is not the same as "actually
shows the story": a 600px header banner or sponsor image survives that size filter
just as easily as a real benchmark chart. So this step asks the language model to
look at the topic's candidate images and pick the single one that depicts the
story — or to pick nothing when the pool is only logos and adverts.

Two pieces live here:

- `gather_candidates` recovers the topic's image pool. It does not re-read any
  HTML; it gathers the candidate images already attached to the topic's source
  emails into one list. (Each `Story` remembers its source email's id, so we can
  find them.)
- `select_image` makes the choice. The model never sees or invents a url: it is
  shown a numbered list and returns just the index it picked (or null). Our code
  turns that index back into the real `CandidateImage`, so the answer is always
  one of the images we sent or `None`.

A known limit: the model chooses from metadata only — each image's alt text and
pixel size — never the picture itself. How well that works depends on the sender.
Some newsletters write the story headline into the image's alt text, which is a
strong signal; others leave alt text empty, and then the choice is close to a
guess. Improving the empty-alt case means teaching the parser to remember where
each image sat in the text, which is a separate change in the parser, not here.
"""

from groq.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.ingest.parser import CandidateImage, ParsedEmail
from app.llm.client import LLMClient, parse_structured
from app.pipeline.cluster import Topic


class ImageChoice(BaseModel):
    """The model's answer: which candidate it picked, by position in the list.

    `index` points at one image in the numbered list we showed the model. It is
    `None` when the model judged that none of the candidates illustrate the story.
    Our code also treats an index outside the list as "no image", so a stray
    number can never reach back into real data.
    """

    index: int | None = None


# Hand-written, and meant to be tweaked as you read real replies: it tells the
# model what "illustrates the story" means and, just as importantly, what to
# reject, so a logo or banner that slipped past the size filter is not chosen.
_SYSTEM_PROMPT = (
    "You pick the one image that best illustrates a news topic. You are given the "
    "topic's label, the titles of its stories, and a numbered list of candidate "
    "images, each with its alt text and pixel size. Choose the single image that "
    "shows the story's own content — a chart, a screenshot, a product photo, a "
    "diagram. Do not pick a logo, masthead, banner, advert, or other decoration. "
    "Return the index of the image you chose. If none of the candidates illustrate "
    "the story, return null instead of forcing a pick."
)


def gather_candidates(
    topic: Topic, emails_by_id: dict[str, ParsedEmail]
) -> list[CandidateImage]:
    """Gather, into one list, the candidate images from the emails this topic's stories came from.

    `emails_by_id` maps a `ParsedEmail.id` to that email, so each story's
    `source_item_id` can be looked up. We walk the topic's stories, find their
    source emails, and collect those emails' candidate images. Two kinds of
    repeat are dropped: a topic often holds several stories from the same email
    (visit each source email once), and two different emails can reference the
    exact same picture (keep each url once). A story whose source email is not in
    the map is skipped rather than treated as an error.
    """
    pool: list[CandidateImage] = []
    seen_source_ids: set[str] = set()
    seen_urls: set[str] = set()
    for story in topic.stories:
        if story.source_item_id in seen_source_ids:
            continue
        seen_source_ids.add(story.source_item_id)
        email = emails_by_id.get(story.source_item_id)
        if email is None:
            continue
        for image in email.candidate_images:
            if image.url in seen_urls:
                continue
            seen_urls.add(image.url)
            pool.append(image)
    return pool


def _dimensions_text(image: CandidateImage) -> str:
    """Describe an image's size, or say it is unknown when the email omitted it."""
    if image.width is not None and image.height is not None:
        return f"{image.width}x{image.height} px"
    return "size unknown"


def _candidate_block(index: int, image: CandidateImage) -> str:
    """Show one image to the model as a single numbered line: index, alt, size."""
    alt = image.alt.strip() or "(no alt text)"
    return f"[{index}] alt: {alt} | {_dimensions_text(image)}"


def _user_prompt(topic: Topic, candidates: list[CandidateImage]) -> str:
    """Lay out the topic, its story titles, and the numbered candidate images.

    The topic label and story titles tell the model what the picture should be
    about; the numbered list is what it chooses from, by index.
    """
    titles = "\n".join(f"- {story.title}" for story in topic.stories)
    listing = "\n".join(
        _candidate_block(index, image) for index, image in enumerate(candidates)
    )
    return f"Topic: {topic.label}\nStories in this topic:\n{titles}\n\nCandidate images:\n{listing}"


def select_image(
    topic: Topic,
    candidates: list[CandidateImage],
    *,
    client: LLMClient | None = None,
) -> CandidateImage | None:
    """Pick the candidate image that illustrates `topic`, or `None` for none.

    An empty pool returns `None` straight away, with no model call. Otherwise the
    model is shown the numbered candidates and returns one index (or null). We
    resolve that index back to the real image; a null or out-of-range index
    becomes `None`. So the result is always one of the images in `candidates` or
    `None` — never an invented url, and "no good image" is a real outcome rather
    than a forced pick.

    Pass `client` only in tests, to use a fake connection instead of the real Groq
    one.
    """
    if not candidates:
        return None

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(topic, candidates)},
    ]
    choice = parse_structured(messages=messages, schema=ImageChoice, client=client)

    index = choice.index
    if index is None or not (0 <= index < len(candidates)):
        return None
    return candidates[index]
