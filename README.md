# Hedwig

Your newsletter subscriptions, distilled by AI into a daily briefing

Hedwig ingests newsletter emails, segments each email into its individual stories, clusters related stories across newsletters into topics, and summarizes each topic with citations back to the original sources. The web frontend lets you browse past digests and search by topic, and a RAG-powered chat lets you ask questions over the entire archive.

The project is also a vehicle for practicing Applied AI end to end: prompt engineering, agentic pipelines, RAG, and evals — all in one build.

![Hedwig v1](https://github.com/initrc/hedwig/blob/main/assets/hedwig-v1.png)

## Architecture

```
ImapSource ─┐
(IMAP)      ├──> EmailSource ──> Parser ────> Pipeline ──> Digest ──┬──> SQLite
LocalEml    ┘    (interface)     (html →      (segment →            ├──> ChromaDB
(.eml files)                      clean text)  cluster →            └──> GET /digests
                                               summarize)
```
At startup the backend auto-runs the digest pipeline iff new content is
available: per-file detection for `samples`, once-per-UTC-day for `imap` (with
gap recovery — fetch resumes from the last digest's date).

**Stack:**

- Python backend (FastAPI) that coordinates ingestion, the LLM pipeline, and RAG chat
  - `DeepSeek-v4-Flash` for the pipeline stages (segment, cluster, summarize) and for generating chat answers from retrieved context
  - `OpenAI text-embedding-3-small` for embedding newsletter text into the RAG vector store and embedding user queries at search time
- Next.js / React / shadcn frontend, served as a single-page web app
- SQLite for digest persistence
- ChromaDB (on-disk) for the vector store

The backend and frontend communicate through a Next.js rewrite proxy (`/api/*` → `http://localhost:8000/*`), so the browser only ever issues same-origin requests and no CORS configuration is needed.

## Backend processes

### Ingestion and parsing

The backend starts by fetching raw newsletter emails through an `EmailSource` interface (`backend/app/ingest/source.py`).

- **LocalEmlSource** reads `.eml` files from `backend/samples/`. This is the default and works offline with no network dependency.
- **ImapSource** connects to an IMAP mailbox (Gmail via app password) and fetches messages filtered by a sender allowlist (`IMAP_SENDERS`) and a fetch start date. On the first run it looks back `IMAP_INITIAL_SINCE_DAYS` days; subsequent runs resume from the last digest's date so a downtime gap is recovered in one fetch. Selectable at runtime via `EMAIL_SOURCE=imap`.

Each raw email flows through the parser (`backend/app/ingest/parser.py`), which extracts the HTML body, strips it to clean readable text (via `readability-lxml` + BeautifulSoup), collects candidate images (filtering out sub-100px junk like logos and tracking pixels), and captures any "view in browser" URL. The output is a `ParsedEmail` — a normalized structure with `id`, `source`, `subject`, `received_at`, `clean_text`, and `candidate_images`.

### The digest pipeline

The digest pipeline is the heart of the project (`backend/app/pipeline/digest.py`). It takes the day's `ParsedEmail` objects and runs them through four sequential LLM stages, each with validated structured output:

1. **Segment** (`segment.py`) — Splits each newsletter email into its distinct stories. A single newsletter often bundles many unrelated stories (product launches, market news, sponsor ads). The LLM extracts each story as a title + body, skipping boilerplate like greetings and sign-offs. Outputs `Story` objects with stable ids derived from the source filename.

2. **Cluster** (`cluster.py`) — Groups all the day's stories into topics. The LLM gets every story's id, title, and a short snippet, then proposes topic groups with labels. The code resolves ids back to real stories, drops any hallucinated ids, places each story in exactly one topic, and orphans any ungrouped story into its own single-story topic.

3. **Summarize** (`summarize.py`) — For each topic, the LLM writes a tight synthesis across all its source stories, with inline citations that reference specific source items. The code validates that every cited id was actually part of that topic's input stories.

4. **Image select** (`image.py`, feature-flagged off) — For each topic, the LLM picks which candidate image best illustrates the story (vs. logos or ads). Disabled because the newsletters we tested with rarely contain publishable images — the candidates are mostly logos, tracking pixels, and sponsor banners, so there is no quality image to select in the first place.

The final `Digest` is a Pydantic model with a date and a list of topics, each carrying a label, summary, source list (with original URLs for the frontend's "view original" links), and an optional image.

### Storage

Digests are persisted to SQLite (`backend/app/storage/digest_store.py`). Each digest is stored as a row with its full JSON payload and a list of ingested source ids — this lets the runner skip already-processed emails on restart, making startup idempotent.

The store also tracks which `source_id`s have been ingested into which digest date, preventing duplicate processing across restarts.

### RAG chat

The chat system (`backend/app/rag/`) is a full retrieval-augmented generation pipeline:

1. **Chunking** (`chunk.py`) — Stories are split into overlapping chunks (512 characters with 128-character overlap), respecting sentence boundaries. At this size each chunk covers roughly two or three sentences, narrow enough that a focused question lands on a highly relevant chunk instead of a dilute blend of unrelated passages.

2. **Embedding** (`embed.py`) — Chunks are embedded with OpenAI text-embedding-3-small (1536-dimensional vectors).

3. **Vector store** (`chroma_store.py`) — ChromaDB stores the vectors on disk at `backend/db/chroma/`, using cosine distance for similarity search. Metadata filtering supports scoped queries by topic label.

4. **Indexing** (`index.py`) — Stories are chunked and embedded per-story, so a source that contributes to multiple topics only indexes each story once. After each new digest, new chunks are embedded and inserted incrementally.

5. **Query** (`ask.py`) — On a user question, the backend embeds the query, retrieves the top-15 most similar chunks, and passes them to the LLM with a system prompt that enforces strict anti-hallucination rules (no invented numbers or dates, mandatory citations even for negative claims, no publisher-name inference from internal identifiers). A guardrail checks retrieval confidence: if the highest cosine similarity score is below 0.35, the system refuses to answer rather than hallucinating. The threshold is calibrated to the embedding model. Real matches on this corpus score 0.45–0.60, while off-topic questions peak at ~0.24.

Scoped chat (`POST /chat?topic_label=...`) restricts retrieval to chunks from a single topic, powering the per-topic chat in the frontend's detail panel.

### Auto-run on startup

On startup, the backend checks whether new emails need processing (`backend/app/runner.py`). The trigger differs by source: for `EMAIL_SOURCE=samples`, it runs whenever a sample file has not yet been digested (compared by filename); for `EMAIL_SOURCE=imap`, it runs once per UTC day, fetching from the last digest's date forward so a multi-day downtime gap is recovered in one run. Either way, the digest pipeline spawns on a daemon thread so the server is immediately responsive while the LLM works. `GET /status` reports either `{"state": "running", "email_count": N}` or `{"state": "idle", "last_digest_at": ...}`. The frontend polls this endpoint every 30 seconds while a run is in progress and stops once idle.

### LLM client

All LLM calls go through the `LLMClient` Protocol (`backend/app/llm/protocol.py`). The real implementation is `OpenAIClient` (`backend/app/llm/client.py`), which wraps the OpenAI SDK pointed at `https://api.deepseek.com` (DeepSeek's API is OpenAI-compatible). Fake implementations (`backend/app/llm/fake_client.py`) let tests and evals run without network calls.

The Protocol defines a single `ask()` method — callers describe what they want (a structured Pydantic output from a prompt), and each implementation decides how to produce it. The shared `_ClientBase` template handles schema instruction prepending, reply guards, and Pydantic validation, so fake and real clients get the same validation for free.

DeepSeek is used for every LLM step in the project:

- The three pipeline stages (segment, cluster, summarize)
- The RAG answer generation (answering user questions from retrieved context)
- The eval judge (scoring summary and answer quality on a faithfulness/conciseness/coherence rubric)

Embedding is the only step that uses a different provider — OpenAI text-embedding-3-small, via a separate `OpenAI` client instantiated in `backend/app/rag/embed.py`.

### Evals

The eval suite (`backend/evals/`) measures the RAG pipeline stages — indexing (chunking + embedding), retrieval, and faithfulness — plus the digest pipeline's clustering and summarization. Every eval produces a pass/fail result with a 0–1 score and a human-readable detail; the markdown scorecard is the single source of truth for quality regressions.

**How it runs.** `uv run python evals/run.py` (stubbed, no API keys, CI-safe) proves harness wiring and catches logic errors before live runs. `uv run python evals/run.py --live` scores against the real DeepSeek LLM, OpenAI embeddings, and the on-disk Chroma store. Live runs are written to `evals/baselines/` as dated snapshots for regression tracking. Run from `backend/`.

**What it measures:**

| Eval | What it validates | Latest (live) |
|------|-------------------|--------------|
| Retrieval hit rate (`rag.py`) | Indexing & retrieval: do the top-15 chunks for a golden question include the expected source? | 1.000 |
| Refusal guardrail (`rag.py`) | Retrieval: does the confidence threshold correctly refuse off-topic questions without an LLM call? | 1.000 |
| Answer faithfulness (`rag.py`) | Faithfulness: LLM-as-judge scores RAG answers against their retrieved context on a 3-dimension rubric | 1.000 |
| Summary quality (`summarize.py`) | Faithfulness: same judge rubric applied to each topic summary against its source stories | 0.975 |
| Judge calibration (`summarize.py`) | Faithfulness: delta between LLM judge scores and hand scores on the same summaries | 0.900 |
| Topic assignment (`categorize.py`) | Pipeline: pairwise co-membership accuracy — do the LLM's clusters agree with hand-labeled groupings? | 0.993 |

Additional evals cover pipeline injection probing and prompt-version comparison.

**Design.** All eval functions accept their clients and stores as parameters, so the same function runs identically in stubbed and live mode — only the injected dependencies differ. Fixtures are typed JSON files (`topic_labels.json` for clustering, `golden_qa.json` for retrieval and faithfulness) loaded through Pydantic models. Adding a new eval requires only writing the function and appending it to the runner's eval list — the scorecard renderer is deliberately generic.

## Frontend

The frontend is a single-page Next.js 16 App Router application using Tailwind CSS v4 and shadcn/ui components (`frontend/app/`).

### Digest list

`DigestCardList` (`frontend/components/digest-card-list.tsx`) fetches two endpoints with SWR:

- `GET /api/digests` — all daily digests with their topics and sources
- `GET /api/status` — whether the backend is currently running a digest or is idle

Digests are rendered as a responsive grid of `DigestCard` components, grouped by date. A text filter narrows the visible topics by label. The header shows "Hedwig" with the backend status as a subtitle, and a theme toggle button sits in the top-right corner.

### Detail sheet and scoped chat

Clicking a topic card opens a right-side slide-over panel (`frontend/components/digest-detail-sheet.tsx`) with two sections:

- **Topic detail** — the full summary and a list of all sources, each with a "view original" link that opens the newsletter's browser version in a new tab.
- **Scoped chat** — a mini chat interface wired to `POST /api/chat?topic_label=...`. The user can ask questions about that specific topic, answered from its sources. The conversation resets when switching topics.

## Running the project

### Backend

```bash
cd backend
cp .env.example .env    # add your DEEPSEEK_API_KEY and OPENAI_API_KEY;
                        # set IMAP_* vars for real-email ingestion
uv run fastapi dev
```

On startup, the backend will automatically process any new sample emails and generate a digest. The server is responsive immediately — `GET /status` tracks the background run.

### Frontend

```bash
cd frontend
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). The frontend proxies `/api/*` to the backend at `http://localhost:8000`.

### Environment variables

| Variable | Purpose | Required |
|---|---|---|
| `DEEPSEEK_API_KEY` | LLM for pipeline and chat | Yes |
| `OPENAI_API_KEY` | Embeddings for RAG | Yes |
| `EMAIL_SOURCE` | `samples` (default) or `imap` | No |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_USERNAME` / `IMAP_PASSWORD` | IMAP connection (only for `EMAIL_SOURCE=imap`; Gmail requires an app password) | No |
| `IMAP_SENDERS` | Comma-separated newsletter sender emails (required in IMAP mode) | No |
| `IMAP_INITIAL_SINCE_DAYS` | Days back to fetch on the first IMAP run; subsequent runs resume from the last digest (default 1) | No |
