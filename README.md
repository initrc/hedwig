# Hedwig

Your newsletter subscriptions, distilled by AI into a daily briefing

Hedwig ingests newsletter emails, segments each email into its individual stories, clusters related stories across newsletters into topics, and summarizes each topic with citations back to the original sources. The web frontend lets you browse past digests and search by topic, and a RAG-powered chat lets you ask questions over the entire archive.

The project is also a vehicle for practicing Applied AI end to end: prompt engineering, agentic pipelines, RAG, and evals — all in one build.

![Hedwig v1](https://github.com/initrc/hedwig/blob/main/assets/hedwig-v1.png)

## Architecture

```
LocalEmlSource ──> Parser ────> Pipeline ──> Digest ──┬──> SQLite
(reads .eml)       (html to     (segment →            ├──> ChromaDB
                    clean text)  cluster →            └──> GET /digests
                                 summarize)
```

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

- **LocalEmlSource** reads `.eml` files from `backend/samples/`. This is the default and works offline with no network dependency — it's the only source used today.
- **ImapSource** (stubbed, not yet wired up) will connect to an IMAP mailbox and fetch messages filtered by sender and date. Selectable at runtime via the `EMAIL_SOURCE` environment variable once live.

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

1. **Chunking** (`chunk.py`) — Newsletter text is split into overlapping chunks (~2048 characters with 256-character overlap), respecting paragraph and sentence boundaries.

2. **Embedding** (`embed.py`) — Chunks are embedded with OpenAI text-embedding-3-small (1536-dimensional vectors).

3. **Vector store** (`chroma_store.py`) — ChromaDB stores the vectors on disk at `backend/db/chroma/`, using cosine distance for similarity search. Metadata filtering supports scoped queries by topic label.

4. **Indexing** (`index.py`) — After each new digest is produced, its source texts are chunked, embedded, and inserted into the vector store incrementally.

5. **Query** (`ask.py`) — On a user question, the backend embeds the query, retrieves the top-k most similar chunks, and passes them to the LLM with a prompt that requires citing sources. A guardrail checks retrieval confidence: if the highest similarity score is below 0.5, the system refuses to answer rather than hallucinating.

Scoped chat (`POST /chat?topic_label=...`) restricts retrieval to chunks from a single topic, powering the per-topic chat in the frontend's detail panel.

### Auto-run on startup

On startup, the backend checks whether any sample emails have not yet been processed (`backend/app/runner.py`). If new emails exist, it spawns a daemon thread to run the full digest pipeline in the background, so the server is immediately responsive while the LLM works. `GET /status` reports either `{"state": "running", "email_count": N}` or `{"state": "idle", "last_digest_at": ...}`. The frontend polls this endpoint every 30 seconds while a run is in progress and stops once idle (the digest runs once a day; the next day is a new session).

### LLM client

All LLM calls go through a single function, `parse_structured()` (`backend/app/llm/client.py`). The client is an `OpenAI` SDK instance pointed at `https://api.deepseek.com` (DeepSeek's API is OpenAI-compatible). Every call requests JSON output, validates the response against a Pydantic schema, and logs timing and token usage. The model used is DeepSeek-v4-Flash.

DeepSeek is used for every LLM step in the project:

- The three pipeline stages (segment, cluster, summarize)
- The RAG answer generation (answering user questions from retrieved context)

Embedding is the only step that uses a different provider — OpenAI text-embedding-3-small, via a separate `OpenAI` client instantiated in `backend/app/rag/embed.py`.

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
cp .env.example .env    # add your DEEPSEEK_API_KEY and OPENAI_API_KEY
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
| `IMAP_HOST` / `IMAP_USERNAME` / `IMAP_PASSWORD` | IMAP credentials (only for `EMAIL_SOURCE=imap`) | No |
