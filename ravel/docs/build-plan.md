# Newsletter Digest Agent — Build Plan

A 5-day plan to build a newsletter digest tool that practices Applied AI end to end.
The project ingests subscribed newsletters, uses an LLM agent to cluster + summarize them into
a daily digest, exposes a RAG chat over the archive, and ships with a real eval harness.

**What it does:** turns the pile of newsletters in an inbox into a clean daily briefing — topics
clustered, summarized with citations — plus a chat to ask questions over
the archive. Instantly understandable ("it organizes my newsletters"), and a great vehicle for
practicing prompt engineering, RAG, agentic pipelines, and evals in one build.

---

## Guiding principles

- **The eval harness is the most valuable part.** It's what turns "it worked once" into "I can
  prove quality and catch regressions." Protect time for it — it's Day 5 and it must not get cut.
- **Decouple ingestion behind an interface** so a live run never depends on a flaky network call.
  `EmailSource` with a local `.eml` implementation for offline runs and an IMAP implementation for
  real inboxes.
- **Frontend is the vehicle, not the point.** Keep cards simple; spend saved time on the AI
  internals.
- **Use synthetic/public data only.** No real personal data in the repo — good hygiene for a
  public project.

---

## Architecture at a glance

```
EmailSource (interface)
  ├─ LocalEmlSource   ← offline: reads ./samples/*.eml          (Day 1)
  └─ ImapSource       ← real: dedicated inbox via IMAP          (Day 1, optional)
        │
        ▼
  Parser: HTML → clean text + extract candidate images          (Day 1)
        │
        ▼
  Agent pipeline (the "batch core"):                            (Day 2)
    cluster items by topic → summarize each cluster
      → pick relevant image
        │
        ▼
  Persisted Digest objects (Postgres or SQLite)                 (Day 2)
        │
        ├──────────────► RAG index (embeddings + search)        (Day 3)
        │                     ▲
        ▼                     │
  Next.js dashboard ──── card list → detail Sheet → scoped chat (Day 4)
        │
        ▼
  Eval harness over the structured outputs                      (Day 5)
```

**Stack:** Python (FastAPI) backend for the agent + RAG; Next.js / React / shadcn frontend.
The Python-for-AI + TypeScript-for-frontend split keeps each side idiomatic.

---

## How to split work between Claude Code and writing it yourself

To actually learn the material, hand-write the parts where the understanding lives and delegate
the toil:

- **Write yourself (the learning core):** the agent pipeline prompts and the
  cluster→summarize→extract flow (Day 2), and the eval scoring logic (Day 5). If you only
  hand-write two things, make it these.
- **Delegate to Claude Code (the scaffolding):** project setup, the IMAP/.eml plumbing, HTML
  parsing boilerplate, the FastAPI routes, the shadcn dashboard, and the Dockerfile. Review every
  diff so you understand it, but you don't need to type it.
- **Pair on:** the RAG layer (Day 3) — let Claude Code scaffold the embedding/index code, but
  hand-tune the chunking and the retrieval prompt yourself, since those choices are the
  substance.

A practical loop: write the prompt + pipeline by hand first, get it working on one newsletter,
*then* have Claude Code generalize it, add error handling, and write tests. You learn the
substance; it removes the toil.

---

## Day 1 — Ingestion + parsing

**Goal:** turn raw newsletters into clean structured items on disk.

1. Set up the repo: Python backend (FastAPI + uv or poetry), a `samples/` folder, and a
   throwaway inbox subscribed to a couple of newsletters (or a few RSS feeds as backup).
2. Define the `EmailSource` interface with two implementations:
   - `LocalEmlSource` — reads `.eml` files from `samples/` (your offline source).
   - `ImapSource` — connects via IMAP app password, filters by sender. (Build if time; the
     local source is enough to proceed.)
3. Parse each message into a normalized item: `{id, source, subject, received_at, clean_text,
   candidate_images: [{url, alt, width, height}], original_url}`.
   - Strip HTML to readable text (BeautifulSoup + a readability pass).
   - Collect candidate images with dimensions and alt text — **don't pick one yet**, just gather
     them. Filter obvious junk (< ~100px = logos/tracking pixels).
4. Dump 8–12 parsed items to JSON so Day 2 has stable input.

**Watch out:** newsletter HTML is messy (templated, multi-column, tracking pixels). Budget for it,
but timebox to half a day — don't let parsing eat the AI work.

**End of day:** `samples/*.eml` → clean JSON items, images included as candidates.

---

## Day 2 — The agent pipeline (the batch core) — *hand-write this*

**Goal:** items in → persisted digest out. This is the heart of the project.

1. **Cluster by topic.** Group the day's items into topics. Start simple: one LLM call that takes
   all item titles+snippets and returns topic groupings with labels. (You can upgrade to
   embedding-based clustering later, but LLM grouping is a fine, explainable v1.)
   - **Note (per-story segmentation, surfaced in T0004):** Day 1 parsing produces one item per
     *email*, but a single newsletter usually bundles many distinct stories into that one item
     (subject + concatenated body). Clustering whole emails is too coarse — a 10-story newsletter
     collapses into a single item with one title, so this step can't separate its stories into
     topic cards. Consider a **segmentation step** that splits each newsletter into per-story
     sub-items *before* this clustering pass (most naturally its own LLM call). Decide the item
     granularity (email vs. story) when writing the Day 2 tasks.
2. **Summarize each cluster.** For each topic, prompt the LLM to produce a tight summary that
   synthesizes across its source items, with citations back to which newsletter each claim came
   from. This is your core prompt-engineering surface — iterate on it.
3. **Extract action items (dropped).** Originally a same-pass or follow-up step to pull concrete,
   dated, or actionable points ("NVDA reports Wed", "new model on HuggingFace"). Cut during T0009
   after the real `backend/samples/` newsletters yielded no useful items — every candidate just
   restated the summary, was a "go try this," or came from a sponsor ad. See T0009 Findings. Step
   numbers below are kept as-is so other tasks' "Day 2 step N" references still hold.
4. **Pick the relevant image.** Pass the cluster's candidate images (alt text, dimensions) to the
   LLM and have it select which image actually illustrates the story (e.g., a benchmark chart),
   or none. This filters logos/ads and is a neat bit of prompt engineering.
5. **Structured output.** Force JSON: `{date, topics: [{label, summary, sources[],
   image}]}`. Validate with Pydantic.
6. **Persist** the full digest object (Postgres for the "real" version; SQLite is fine). Store the
   *full* object — the card is just a projection of a few fields; the detail panel needs the rest.

**Learning focus:** write the prompts and the flow by hand. Get it working on one day's items,
inspect the JSON, fix the prompts, repeat. This iteration *is* the skill.

**End of day:** a `POST /digest/run` endpoint that ingests → produces → persists a digest.

---

## Day 3 — RAG layer (chat over the archive) — *pair with Claude Code*

**Goal:** "what did that finance newsletter say about rate cuts last week?" answered with citations.

1. **Index.** Embed the parsed items (chunk first — hand-tune chunk size/overlap and be clear on
   why). Store vectors in a simple store (pgvector, Chroma, or LanceDB).
2. **Retrieve + generate.** On a query, retrieve top-k chunks, pass to the LLM with a
   citation-grounded answer prompt. Return the answer plus which sources it used.
3. **Guardrail:** if retrieval confidence is low, the agent says "I don't have that in your
   newsletters" rather than hallucinating. Small thing, big credibility.
4. Expose `POST /chat` (global) and `POST /chat?topic_label=...` (scoped to one card's sources, for
   Day 4's detail panel).

**End of day:** working RAG chat endpoint with citations and a low-confidence refusal path.

---

## Day 4 — Frontend (Next.js + shadcn)

**Goal:** the product surface. Keep it clean and simple.

1. **Initialize the frontend.** Scaffold `frontend/` with Next.js + shadcn using the Lyra preset:
   ```
   pnpm dlx shadcn@latest init --preset buFywKm --template next
   ```
   Add needed components (`card`, `sheet`, `button`, `input`, `badge`). Wire the
   frontend to the backend at `http://localhost:8000`. Also add `GET /digests` to
   the backend so the frontend can list recent digests, and configure CORS so the
   frontend (port 3000) can reach the backend (port 8000).
2. **Card list**, filterable by category. Each card: title, description, subtle source label,
   optional image (the LLM-selected one from Day 2).
3. **Detail Sheet** on card click (shadcn `Sheet`): full summary, all source citations,
   "view original" link. This is where clustering pays off visually — a topic
   synthesized from several newsletters, each claim cited.
4. **Scoped chat** at the bottom of the Sheet, wired to `POST /chat?topic_label=<label>` — ask questions
   about *that* topic, answered from its sources. The topic id is the `label` string from the digest.
5. **Auto-run digest on startup + status.** No manual button — the backend runs the digest pipeline
   automatically when it starts, but only if there are sample emails not yet digested (already-
   processed source ids are recorded, so restarting is idempotent). The run happens in a background
   thread so the server stays responsive while the LLM works. `GET /status` reports `running` (with
   the email count) or `idle` (with the last digest's timestamp, so the user knows how stale the
   content is). The dashboard header title is "Hedwig" with the status as its subtitle, and polls
   `/status` every 30s while a run is in progress, stopping once idle (the digest runs once a day;
   the next day is a new session). `POST /digest/run` is kept for manual/test use but is no longer
   the primary trigger.

**Timebox to one day.** shadcn makes this fast — hold the line and bank leftover time for Day 5.

**End of day:** click card → Sheet with full detail + scoped chat; digest runs automatically on
backend startup and its status shows in the dashboard header.

---

## Day 5 — Eval harness — *hand-write this; do not cut it*

**Goal:** quantified proof the system works, and a regression check across prompt versions.

1. **Build a labeled set.** Hand-label ~30–50 items: correct topic/category, and a small golden
   Q&A set for the RAG side (question → which source should answer it).
2. **Categorization/summarization evals:**
   - Topic-assignment accuracy vs. your labels.
   - Summary quality via LLM-as-judge against a rubric (faithful to sources? no invented facts?
     concise?). Calibrate the judge against a few of your own human scores so you understand judge
     drift.
   - Did image selection pick a relevant image vs. a logo?
3. **RAG evals:** retrieval hit rate (did the right source come back?), answer faithfulness, and
   does the low-confidence refusal fire on out-of-corpus questions?
4. **Safety/robustness probes:** a few adversarial inputs (prompt-injection text inside a
   newsletter body — "ignore previous instructions") to confirm the pipeline holds up.
5. **Prompt-version comparison:** run the suite against two versions of your summarization prompt
   and show pass-rate deltas — prompts treated as versioned artifacts with regression testing.
6. Output a simple results table (markdown or a tab in the dashboard).

**End of day:** `python evals/run.py` prints a scorecard; you can point to numbers, not vibes.

---

## If you run short on time (cut in this order)

1. Cut `ImapSource` — run from local `.eml` only (the interface still shows the design).
2. Cut the scoped per-card chat — keep one global chat box.
3. Cut prompt-version comparison — keep the core eval scorecard.
4. **Never cut:** the agent pipeline (Day 2) or the core eval scorecard (Day 5). Those are the
   substance.

---

## Design rationale (the decisions worth understanding)

- **Agentic design:** the digest is a pipeline — cluster, summarize, extract, select — with
  structured/validated outputs at each step rather than one mega-prompt, so each stage is
  independently testable.
- **Decoupling for testability:** ingestion sits behind a source interface, so the LLM logic
  doesn't care whether mail comes from IMAP or local files — and you can run it offline with no
  network dependency.
- **RAG with guardrails:** low retrieval confidence triggers a refusal instead of a
  hallucination — the right default anywhere correctness matters.
- **Evals as first-class:** prompts are versioned and run through a regression suite with an
  LLM-as-judge calibrated against human labels, plus adversarial/injection probes.

---

## Stack checklist

- [ ] Python backend: FastAPI, Pydantic, an LLM SDK, BeautifulSoup, feedparser (RSS fallback)
- [ ] Vector store: pgvector / Chroma / LanceDB (pick one)
- [ ] DB: Postgres or SQLite for digest persistence
- [ ] Frontend: Next.js, React, TypeScript, shadcn/ui (Lyra preset: `pnpm dlx shadcn@latest init --preset buFywKm --template next`)
- [ ] Eval: a small harness script + labeled JSON fixtures
- [ ] Throwaway inbox subscribed to a couple of newsletters (or RSS feeds as backup)
