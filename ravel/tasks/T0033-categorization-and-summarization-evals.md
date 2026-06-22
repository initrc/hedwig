---
id: T0033
title: Categorization and summarization evals
status: done
dependencies:
  - T0032
---

# Scope

- Build the categorization/summarization evals (build-plan Day 5 step 2):
  - **Topic-assignment accuracy** vs. the hand-labeled set: run the cluster step (T0008) on the
    labeled stories and score how well the predicted groupings match the labeled topics.
  - **Summary quality via LLM-as-judge** against a rubric: for each topic summary (T0009), have an
    LLM judge it for faithfulness (no invented facts, claims traceable to sources), conciseness, and
    coherence. Calibrate the judge against a few human scores so judge drift is visible.
- ~~**Image-selection relevance:** did the picker choose a relevant image vs. a logo?~~ **Dropped.**
  T0028 disabled topic image selection behind `_SELECT_TOPIC_IMAGES = False` and removed images from
  the frontend, so there is no selected image to score. Preserved here for traceability against the
  build plan; revisit only if T0028 is reverted.

# Acceptance

- A `eval_topic_assignment(stories, labels, *, client=None) -> list[EvalResult]` function runs the
  T0008 `cluster()` step on the labeled stories and scores the predicted grouping against the
  hand-labeled expected topics. The metric is **story co-membership**, not exact label string match
  (LLM labels are free-form): stories the human placed in one topic should land in a single predicted
  topic, and stories in different human topics should not be merged. The chosen metric is named and
  documented in a comment.
- A `eval_summary_quality(digest, *, judge_client=None) -> list[EvalResult]` function runs an
  LLM-as-judge over each topic's summary against a rubric (faithfulness / conciseness / coherence)
  and returns one `EvalResult` per topic plus an aggregate. The judge is a structured LLM call
  (`parse_structured` from T0006) returning per-dimension scores.
- **Judge calibration:** a small set of summaries (3–5) is hand-scored by a human against the same
  rubric, and the judge's scores on the same summaries are recorded alongside. The delta (judge
  drift) is reported as an `EvalResult` so the scorecard shows whether the judge is biased high/low,
  not just the raw scores.
- Tests run **without real API calls** — stub `cluster`'s LLM (`client=`) and the judge LLM
  (`judge_client=`) and assert: the topic-assignment metric scores a perfect grouping at 1.0 and a
  shuffled grouping below 1.0; the judge aggregation turns structured judge output into the right
  `EvalResult`s; calibration delta is computed correctly from a hand-scored fixture.
- `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

# Implementation Notes

- Build-plan reference: `ravel/docs/build-plan.md` Day 5 step 2 (lines 201–205): "Topic-assignment
  accuracy vs. your labels. Summary quality via LLM-as-judge against a rubric (faithful to sources?
  no invented facts? concise?). Calibrate the judge against a few of your own human scores so you
  understand judge drift." The plan marks the eval scoring logic as **hand-write-it** learning core
  (lines 66–67) — iterate the judge prompt like you iterate the summarize prompt.
- **Topic-assignment metric (hand-write this):** because cluster labels are LLM-generated strings,
  comparing them by equality is meaningless. Score by membership: two stories the human put in one
  topic should share a predicted topic, and stories in different human topics should split. A simple,
  explainable choice is pairwise accuracy over story pairs — "for each pair of stories the human
  co-grouped, did the model co-group them too?" Document the formula in the module docstring. Avoid
  pulling in scikit-learn for one metric; if you use adjusted Rand index, justify it. The point is a
  number you can defend, not a library call.
- **Inputs:** the labeled stories come from T0032's `dataset.py`. For the topic-assignment eval,
  reconstruct the `Story` objects the clusterer expects (`backend/app/pipeline/segment.py`) from the
  fixture (the fixture carries `source_item_id`, `title`, `text`). For the summary-quality eval, run
  the real summarize step on the predicted topics (or load a persisted `Digest` from the T0012 store
  via `DigestStore.list_recent`, `backend/app/storage/digest_store.py:151`) and judge its
  `DigestTopic.summary` + `sources`.
- **LLM-as-judge design (the learning core):**
  - Reuse `parse_structured` from `backend/app/llm/client.py:111` with a Pydantic rubric schema
    (e.g. `RubricScore(faithfulness: float, conciseness: float, coherence: float, rationale: str)`).
  - The judge prompt gives the topic's stories (source text) and the summary, and asks: is every
    claim in the summary supported by the source text? Is anything invented? Is it concise? Score
    each dimension 0.0–1.0. Iterate this prompt — judge drift is the thing this task teaches you to
    see, so do not skip the calibration step.
  - Faithfulness is the dimension that matters most (it is the same property T0009's citation
    check enforces in code); weight the aggregate toward it and document the weighting.
- **Calibration:** hand-score 3–5 summaries on the same rubric (record the scores in a fixture under
  `backend/evals/fixtures/`, e.g. `judge_calibration.json`). Run the judge on the same summaries and
  emit an `EvalResult` whose `detail` states the mean per-dimension delta (judge minus human). This
  is what "understand judge drift" (build-plan line 204) means in practice — a number on the
  scorecard, not a vibe.
- **Citation faithfulness is already partly checked in code** (`_resolve_sources` in
  `backend/app/pipeline/summarize.py:85` drops invented source ids). The judge evaluates a stronger
  property: that the summary's *textual claims* are backed by the cited sources, not just that the
  cited ids are valid. Don't conflate the two — the code check is id validity, the judge is claim
  support.
- **Cost guard:** the judge is an extra LLM call per topic. Judge only the topics in the labeled set
  (a handful), not every digest ever produced. The runner (T0037) gates real calls behind a
  `--live`/env flag; respect that here by taking `judge_client=None` (default client) and letting
  tests inject a fake.
- **Image-selection sub-item:** dropped per T0028. `DigestTopic.image` is always `null` with
  `_SELECT_TOPIC_IMAGES = False` (`backend/app/pipeline/digest.py`), so there is no selection to
  score. Do not write an image-relevance eval. If T0028 is ever reverted, add the eval then; the
  build-plan line 205 reference is left struck through above for traceability (same pattern T0009
  used for action items).
- **Out of scope:** the runner and markdown scorecard (T0037), prompt-version comparison (T0036,
  which reuses `eval_summary_quality`), RAG evals (T0034), and safety probes (T0035).

# Execution Split

## What AI agent does

- Write `backend/evals/categorize.py` — `eval_topic_assignment()`. Runs the cluster step on
  labeled stories, scores predicted groupings against hand-labeled topics using pairwise
  co-membership accuracy. Includes the metric formula documented in the module docstring.
- Write `backend/evals/summarize.py` — `eval_summary_quality()`. LLM-as-judge against the
  faithfulness/conciseness/coherence rubric, plus calibration delta computation that compares
  judge scores to the human hand scores from the fixture.
- Design the judge prompt — a structured LLM call via `parse_structured` with a Pydantic rubric
  schema. Iterate the prompt against the calibration fixture until the delta is reasonable.
- Write `backend/evals/fixtures/judge_calibration.skeleton.json` — the schema template the human
  fills in.
- Write tests for both eval modules. All tests stub the LLM — no real API calls. Assert:
  pairwise metric scores a perfect grouping at 1.0 and a shuffled grouping below 1.0; judge
  aggregation turns structured output into the right `EvalResult`s; calibration delta computes
  correctly from the hand-scored fixture.
- Ensure `uv run pytest`, `uv run ruff check`, and `uv run mypy` all pass.

## What the human does

Only one thing needs human judgment: scoring summaries against the rubric so we can calibrate
the LLM judge. The steps below walk through producing the `judge_calibration.json` fixture.

### Step 1: Dump existing topic summaries with their source stories

From the `backend/` directory, run this to see every topic summary alongside the stories that
fed it:

``bash
uv run python -c "
from app.storage.digest_store import DigestStore

store = DigestStore()
digests = store.list_recent(limit=5)

for d in digests:
    for t in d.topics:
        print('=' * 60)
        print(f'TOPIC: {t.label}')
        print(f'SUMMARY: {t.summary}')
        print()
        for s in t.sources:
            print(f'  SOURCE: {s.source} — {s.subject}')
            print(f'  TEXT: {s.clean_text[:500]}...')
            print()
        print()
"
``

The dump truncates source text at 500 chars for readability. If the output is too long, pipe it
to a file: `... > /tmp/digest_dump.txt` and read it there.

### Step 2: Pick 3–5 topics to score

Choose topics that vary in quality — pick at least one summary you think is good, one that is
mediocre, and one that has issues (invented facts, too vague, misleading). Variety makes the
calibration more informative. The 2026-06-17 and 2026-06-18 digests together have 20 topics to
choose from.

### Step 3: Score each summary on three dimensions

For each summary you pick, read its source stories carefully (you'll need the full text, not
just the 500-char preview from the dump — see Step 4). Then assign a score from 0.0 to 1.0 on
each dimension:

| Dimension | What it means | 1.0 looks like | 0.0 looks like |
|---|---|---|---|
| **Faithfulness** | Is every claim in the summary backed by the source text? Nothing invented, nothing distorted. | Every sentence traces to a source; nothing added. | Hallucinated facts, wrong numbers, or claims absent from sources. |
| **Conciseness** | Is the summary tight? No wasted words, no repetition, no filler. | Every word earns its place; reads efficiently. | Meandering, repeats itself, includes irrelevant detail. |
| **Coherence** | Does it read as a unified paragraph, not a list of disconnected facts? Logical flow, good transitions. | Flows naturally from start to finish; one thought leads to the next. | Reads like bullet points glued together; jarring jumps. |

**Faithfulness is the most important dimension.** It is the one the aggregate weights toward.
Be especially careful scoring it — note any specific claims that feel unsupported by the
sources, even if you are not 100% sure.

### Step 4: Get the full source text for your chosen topics

The Step 1 dump truncates source text. To get the full `clean_text` for just the topics you
picked, run this script (replace the topic labels in the `wanted` set):

``bash
uv run python -c "
from app.storage.digest_store import DigestStore

wanted = {'Cursor announcements', 'AI coworker tools'}  # <-- your topics here

store = DigestStore()
for d in store.list_recent(limit=5):
    for t in d.topics:
        if t.label in wanted:
            print('=' * 60)
            print(f'TOPIC: {t.label}')
            print(f'SUMMARY: {t.summary}')
            print()
            for s in t.sources:
                print(f'  SOURCE: {s.source} — {s.subject}')
                print(f'  FULL TEXT: {s.clean_text}')
                print()
            print()
"
``

### Step 5: Record scores in the calibration fixture

Create `backend/evals/fixtures/judge_calibration.json` with this schema (one entry per topic
you scored):

``json
[
  {
    "topic_label": "Cursor announcements",
    "summary": "Cursor has made two major announcements...",
    "stories": [
      {
        "title": "Cursor announces Origin, a git hosting platform built for AI agents",
        "text": "Cursor just announced Origin..."
      },
      {
        "title": "SpaceX acquires Cursor for $60B",
        "text": "SpaceX has exercised its option..."
      }
    ],
    "human_scores": {
      "faithfulness": 0.9,
      "conciseness": 0.8,
      "coherence": 0.85,
      "notes": "Optional: explain why you scored this way. For faithfulness, note any claims you flagged as invented or unsupported by the source text."
    }
  }
]
``

- `topic_label`: copy from the dump output.
- `summary`: copy the full summary text from the dump output.
- `stories`: for each source in the topic, use `subject` as `title` and the full `clean_text` as
  `text`. If a topic draws from multiple sources, include all of them — the judge needs every
  story to evaluate faithfulness.
- `human_scores`: your three scores (each 0.0–1.0). The `notes` field is optional but helpful —
  it captures your reasoning so we can debug judge drift later.

### Step 6: Hand back to AI agent

Once the fixture is written, I will:
1. Build `eval_summary_quality()` with the LLM-as-judge, wired to the calibration fixture.
2. Run the judge on the same summaries you scored.
3. Compute per-dimension deltas (judge minus human) and report them.
4. Show you the results so you can see judge drift — and iterate the judge prompt if the delta
   is large on any dimension, especially faithfulness.

### How to run the real LLM judge

Both eval functions take an optional `client`/`judge_client` parameter. When you pass
`None` (the default), they use the real DeepSeek connection. When you inject a
`FakeClient`, they run offline — that's how the tests work.

**Run the judge on calibration entries** (compares judge scores to your hand scores):

```bash
cd backend && uv run python -c "
from evals.summarize import eval_judge_calibration

results = eval_judge_calibration()

for r in results:
    print(f'{r.name}')
    print(f'  passed: {r.passed}')
    print(f'  score:  {r.score:.3f}')
    print(f'  detail: {r.detail}')
    print()
"
```

**Run topic-assignment eval** (clusters the labeled stories and scores against your labels):

```bash
cd backend && uv run python -c "
from evals.dataset import load_topic_labels
from evals.categorize import eval_topic_assignment
from app.pipeline.segment import Story

labeled = load_topic_labels()
stories = [
    Story(id=s.story_id, source_item_id=s.source_item_id, title=s.title, text=s.text)
    for s in labeled
]
labels = {s.story_id: s.expected_topic for s in labeled}

results = eval_topic_assignment(stories, labels)
for r in results:
    print(f'{r.name}: score={r.score:.3f} passed={r.passed}')
    print(f'  {r.detail}')
"
```

**Run summary-quality eval** on a digest from the store:

```bash
cd backend && uv run python -c "
from evals.summarize import eval_summary_quality
from app.storage.digest_store import DigestStore

store = DigestStore()
digest = store.list_recent(limit=1)[0]

results = eval_summary_quality(digest)
for r in results:
    print(f'{r.name}: score={r.score:.3f} passed={r.passed}')
    print(f'  {r.detail}')
    print()
"
```
