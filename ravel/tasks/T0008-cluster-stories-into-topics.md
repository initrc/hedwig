---
id: T0008
title: Cluster stories into labeled topics
status: done
dependencies:
  - T0006
  - T0007
---

# Scope

- Add the clustering step: group the day's `Story` sub-items (from T0007) into topics, each with a concise
  human-readable label. One LLM call takes all story titles + short snippets and returns topic groupings.
- Output a `Topic` (or `Cluster`) structure that lists which stories belong to it, so downstream steps
  (summarize T0009, image-select T0010) operate per-topic.

# Acceptance

- A Pydantic model represents a cluster: a `label` plus the set of member stories (or their ids). It
  validates via Pydantic.
- A `cluster(stories: list[Story]) -> list[Topic]` function exists; every story id referenced by a returned
  topic corresponds to an input `Story`, and (unless deliberately dropped) every input story lands in exactly
  one topic.
- The step uses the T0006 structured-output helper with a Pydantic schema.
- Tests run **without real API calls** (stub the LLM helper) and cover: stories about the same subject land in
  one topic; unrelated stories split into separate topics; the mapping back to input story ids is total and
  valid (no invented or dropped ids unless intended).
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 2 step 1 (lines 107–111). The plan recommends a single
  LLM grouping call as an explainable v1 ("You can upgrade to embedding-based clustering later"). Do the
  simple LLM version here; the embedding upgrade is out of scope and belongs to Day 3's RAG work.
- Input: `Story` list from T0007 (`backend/app/pipeline/segment.py`). Suggested module:
  `backend/app/pipeline/cluster.py`.
- **Prompt + id discipline:** send the model the story `id` + `title` + a short snippet of `text`, and ask it
  to return groups referencing story ids. Validate in code that returned ids are a subset of the input ids;
  drop or raise on hallucinated ids rather than trusting the model. Generate topic labels from the model but
  keep them short.
- **Schema shape:** wrap the list of clusters in a top-level object for `output_format` (e.g.
  `Clustering` with `topics: list[TopicSpec]`, each `TopicSpec` carrying `label` and `story_ids`). Resolve
  ids back to `Story` objects in code so later steps don't re-look-them-up.
- **Reasoning depth:** clustering benefits from the model reasoning over the whole set at once — consider
  raising Groq's `reasoning_effort` (exposed by the T0006 helper) for this call. Keep all stories in a single
  call for a day's digest (the corpus is 8–12 emails → a few dozen stories, well within context).
- Decide and document the policy for a story that fits no topic (e.g. a singleton "Other"/own-topic) so the
  mapping stays total; the acceptance test pins whichever choice you make.

# Decisions

- Module: `backend/app/pipeline/cluster.py`. `cluster(stories, *, client=None) -> list[Topic]` mirrors
  `segment`'s shape (keyword-only `client` for test injection).
- Schema: model returns `Clustering { topics: list[DraftTopic{ label, story_ids }] }`; code resolves ids back
  to `Story` objects on the public `Topic { label, stories: list[Story] }`. `DraftTopic` follows the `Draft*`
  naming from `segment.py`'s `DraftStory` (the model's raw reply before our code resolves it), in preference
  to the task note's suggested `TopicSpec`.
- **Totality / id discipline (all enforced in code, not trusted to the model):**
  - hallucinated id (not in input) → dropped;
  - story named in two topics → kept in the first, ignored after (a topic left empty this way is dropped);
  - story the model groups with nothing → becomes its own one-story topic, labelled with its title (falling
    back to "Other" if the title is empty).
  So every returned topic references real input stories, and every input story lands in exactly one topic.
- `reasoning_effort="high"` for this call (vs the helper's "low" default), since grouping weighs the whole
  set at once. Empty input short-circuits to `[]` with no model call.
