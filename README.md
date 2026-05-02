# LogiScout — RAG Server

> The retrieval-augmented generation backbone of **LogiScout**, a software-incident and code-investigation assistant.

**Stack:** FastAPI · Qdrant · ClickHouse · Gemini · Groq · `bge-small-en-v1.5`

This repository is the **RAG server for LogiScout**. It owns the retrieval and response pipeline end to end, and also runs the ingestion paths for the data it serves at query time — **GitHub commits** and **postmortems** are ingested here directly. Log vectors are produced by a separate log-vectorization service; this server retrieves them and joins each hit back to the raw rows in ClickHouse at query time.

Alongside the core RAG flow, the server provides conversation-maintenance endpoints (rolling chat summaries and project-level "vague context") so that long-running sessions stay coherent without exhausting the LLM context window.

---

## Architecture at a Glance

```
                       ┌─────────────────────────────────────────────────────┐
User prompt  ────────► │  Response Pipeline   (primary)                      │ ───► Streamed answer
                       │  intent → retrieve (Qdrant) → enrich (ClickHouse)   │      (NDJSON over HTTP)
                       │       → answer (LLM)                                │
                       └─────────────────────────────────────────────────────┘
                                          ▲                ▲
                                          │                │
                            ┌─────────────┴────┐   ┌───────┴────────┐
                            │ Qdrant            │   │ ClickHouse     │
                            │ {project_id}_*    │   │ logging.logs   │
                            └───────────────────┘   └────────────────┘
                                          ▲
                  ┌───────────────────────┼─────────────────────────────┐
                  │                       │                             │
        GitHub push  ─► commit            postmortem ingester          log vectorizer
        ingestion (in this repo)          (separate service)            (separate service)
        → {project_id}_commits            → {project_id}_postmortem    → {project_id}_logs
```

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
# source venv/bin/activate       # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables (see below)
cp .env.example .env             # then fill in your keys

# 4. Start the server
python run.py
```

Interactive API docs: **http://localhost:8000/docs**

---

## Environment Variables

All configuration is loaded by `app/core/settings.py` from a `.env` file in the project root.

```dotenv
# ── Application ──────────────────────────────────────────────
APP_NAME=LogiScout
APP_VERSION=1.0.0
DEBUG=true
API_V1_PREFIX=/api/v1
ALLOWED_ORIGINS=["*"]

# ── GitHub Webhook (commit ingestion) ────────────────────────
GITHUB_WEBHOOK_SECRET=<your-webhook-secret>

# ── LLM Fallback Chain (Gemini primary, Groq fallback) ───────
GEMINI_KEY=<your-gemini-key>
GROQ_API_KEY=<your-groq-api-key>
GROQ_INTENT_MODEL=llama-3.3-70b-versatile

# ── Qdrant (Vector DB) ───────────────────────────────────────
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# ── Response Pipeline ────────────────────────────────────────
RESPONSE_TOP_K=5
RESPONSE_SCORE_THRESHOLD=0.0

# ── ClickHouse (Related Logs Enrichment) ─────────────────────
CLICKHOUSE_HOST=<host>
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=<password>
CLICKHOUSE_DATABASE=logging
CLICKHOUSE_LOGS_TABLE=logs
CLICKHOUSE_RELATED_LOGS_LIMIT=50
```

| Variable | Required | Description |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | ✅ | HMAC-SHA256 secret shared with the GitHub webhook (commit ingestion) |
| `GEMINI_KEY` | ✅ | Google Gemini API key — primary LLM provider |
| `GROQ_API_KEY` | ✅ | Groq API key — fallback LLM provider |
| `QDRANT_URL` | ❌ | Qdrant connection URL (default `http://localhost:6333`) |
| `QDRANT_API_KEY` | ❌ | Qdrant Cloud API key (omit for local Docker) |
| `RESPONSE_TOP_K` | ❌ | Vector hits per source (default `5`) |
| `RESPONSE_SCORE_THRESHOLD` | ❌ | Minimum similarity score for retrieval (default `0.0`) |
| `CLICKHOUSE_*` | ✅ for log enrichment | Connection + database/table for raw log lookup by `correlationId` |

> **Note:** Commit ingestion currently supports **public GitHub repositories only**.

---

## API Endpoints

All endpoints are mounted under `API_V1_PREFIX` (default `/api/v1`).

### Response (RAG) — primary

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/response` | Run the response pipeline and stream NDJSON chunks |

Request body:

```json
{
  "project_id": "1234abcd",
  "user_prompt": "Why did /auth/login start returning 500s last night?",
  "vague_context": "<optional project memory>",
  "chat_context":  "<optional prior turns>"
}
```

The response is `application/x-ndjson` — one JSON object per line:

```jsonc
{"event":"status",  "data":{"stage":"intent_detection"}}
{"event":"intent",  "data":{"intent":"...", "needs_logs":true, "needs_commits":false, ...}}
{"event":"status",  "data":{"stage":"retrieval"}}
{"event":"status",  "data":{"stage":"log_enrichment"}}
{"event":"status",  "data":{"stage":"answer_generation"}}
{"event":"answer",  "data":{"text":"...", "log_context":[...], "commit_context":[...], ...}}
{"event":"done",    "data":{"ok":true,  "sources":[...]}}
```

The terminal `done` event is **always** emitted, even on error, so clients can close the stream cleanly.

### Conversation Maintenance

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat_summary` | Update a chat session's rolling summary (called every ~10 new messages) |
| `POST` | `/vague_context/summarize` | Fold a chat summary back into a project's evergreen "vague context" |

### GitHub Commit Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/{project_id}/github` | Receive GitHub push events for a project |
| `GET`  | `/commits/timeline` | Latest 5 commits across all projects |
| `GET`  | `/commits/{project_id}/timeline` | Latest 5 commits for a specific project |

---

## Response Pipeline (primary focus)

A user prompt is resolved in four stages, with status frames streamed at every transition:

```
POST /response
  │
  ├─ 1. IntentDetector
  │     LLM (Gemini → Groq) classifies the question and decides which
  │     buckets to retrieve: needs_logs / needs_commits / needs_postmortem
  │
  ├─ 2. VectorRetrievalStep
  │     Embeds the prompt with bge-small-en-v1.5
  │     Queries the project-scoped Qdrant collections that intent flagged
  │     Normalizes hits to {id, score, semantic_text, metadata}
  │
  ├─ 3. LogEnrichmentStep            (only when needs_logs=true)
  │     Collects correlation_id from each log-vector hit's metadata
  │     One batched ClickHouse query:
  │         SELECT * FROM {db}.{table}
  │         WHERE correlationId IN %(ids)s
  │         ORDER BY correlationId, timestamp DESC
  │         LIMIT N BY correlationId
  │     Attaches rows under metadata.related_logs on each hit
  │     Failures are logged and swallowed — the pipeline still answers
  │
  └─ 4. AnswerGenerator
        Builds a structured prompt from intent + vague + chat + retrieved evidence
        Streams a markdown-formatted answer back via Gemini → Groq fallback
        Evidence-only fallback if both providers fail
```

Each project's data lives in three Qdrant collections, scoped by `project_id`:

| Suffix | Source |
|---|---|
| `_commits`     | Indexed by the GitHub commit ingestion in this server |
| `_postmortem`  | Indexed by an external postmortem authoring/ingestion service |
| `_logs`        | Indexed by an external log-vectorization service; enriched at query time from ClickHouse `logging.logs` |

---

## Commit Ingestion Pipeline (secondary)

A GitHub push event lands at `POST /webhook/{project_id}/github`, the HMAC-SHA256 signature is verified, and each commit flows through five stages:

```
Webhook Push Event
  │
  ├─ 1. GitHubFetcherService     GitHub API + .patch diff (capped at 4 000 chars)
  ├─ 2. DiffAnalyzerService      Classify change_type, risk_level, affected_systems
  ├─ 3. LLMSummarizerService     Plain-English summary via Gemini → Groq fallback
  ├─ 4. IndexingPrepService      Build semantic_text + flat Qdrant metadata
  └─ 5. VectorStoreService       Embed (bge-small-en-v1.5) and upsert into
                                 {project_id}_commits  (deduped by commit SHA)
```

Commits are also added to an in-memory rolling window (last 5 per project), surfaced via `/commits/timeline`.

---

## Project Structure

```
logiscout-rag-Server/
│
├── run.py                                    # Uvicorn entry point (port 8000)
├── requirements.txt
├── .env                                      # Environment config (not committed)
│
└── app/
    ├── main.py                               # App factory: lifespan, CORS, router mount
    │
    ├── core/
    │   ├── settings.py                       # Pydantic Settings — all env vars
    │   ├── constants.py
    │   └── logging_config.py
    │
    ├── prompts/                              # Centralized prompt templates
    │   ├── intent.py
    │   ├── answer.py
    │   ├── chat_summary.py
    │   └── vague_context.py
    │
    ├── api/
    │   ├── router.py                         # Aggregates all sub-routers
    │   └── routes/
    │       ├── response/                     # POST /response  (NDJSON stream)
    │       ├── chat_summary/                 # POST /chat_summary
    │       ├── vague_context/                # POST /vague_context/summarize
    │       ├── webhook/                      # POST /webhook/{project_id}/github
    │       └── commits/                      # GET  /commits/...
    │
    └── services/
        ├── response_pipeline/                # Response (RAG) pipeline — primary
        │   ├── pipeline.py
        │   ├── config.py
        │   └── pipeline_steps/
        │       ├── intent_detector.py
        │       ├── vector_retrieval.py
        │       ├── log_enrichment.py         # ClickHouse correlation_id lookup
        │       ├── answer_generator.py
        │       └── ID_fallback_chain.py      # Gemini → Groq LLM client
        │
        ├── chat_summary_service/             # Rolling per-chat summarization
        ├── vague_context_service/            # Project-level evergreen context
        ├── summarization_utils.py
        │
        └── github_webhook_service/           # GitHub commit ingestion (5 stages)
            ├── pipeline.py
            └── pipeline_services/
                ├── github_fetcher.py
                ├── diff_analyzer.py
                ├── llm_summarizer.py
                ├── indexing_prep.py
                └── vector_store.py
```

---

## External Dependencies

| Service | Purpose |
|---|---|
| **Qdrant**     | Vector storage for commits, logs, postmortems |
| **ClickHouse** | Source of truth for raw log lines, queried by `correlationId` during retrieval |
| **Gemini**     | Primary LLM (intent detection, answer generation, summarization) |
| **Groq**       | Fallback LLM (model: `llama-3.3-70b-versatile`) |
| **GitHub API** | Structured commit data + raw `.patch` diffs (commit ingestion only) |

The LLM fallback chain is implemented in `app/services/response_pipeline/pipeline_steps/ID_fallback_chain.py` and shared across every component that calls a model.
