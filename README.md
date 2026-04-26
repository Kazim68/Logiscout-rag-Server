# LogiScout — Ingestion Server

A GitHub webhook ingestion server built with **FastAPI**. Receives GitHub push events in real time, processes each commit through a multi-stage pipeline (diff analysis, LLM summarization, vector embedding), and stores enriched semantic documents in **Qdrant** for later retrieval and semantic search.

---

## How It Works

1. GitHub sends a push event to `POST /api/v1/webhook/{project_id}/github`.
2. The server verifies the HMAC-SHA256 signature.
3. For each commit in the payload:
   - **Fetch** — Calls the GitHub API for structured commit data + `.patch` diff.
   - **Analyze** — Deterministic classification of change type, risk level, and affected systems from file paths.
   - **Summarize** — Sends the diff to an LLM (Gemini or Groq) for a plain-English technical summary.
   - **Prep** — Builds a semantic text string and flat metadata payload optimized for embedding.
   - **Store** — Embeds with `bge-small-en-v1.5` and upserts into a project-scoped Qdrant collection (`{project_id}_commits`).
4. Commits are also added to an in-memory rolling window (last 5) and written to `logs/activity.log`.

> **Multi-project support:** Each project gets its own Qdrant collection. One server handles all repos — the `project_id` in the URL and the repo in the webhook payload handle scoping automatically.

---

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment (see below)
cp .env.example .env             # Then fill in your keys

# 4. Start the server
python run.py
```

API docs: **http://localhost:8000/docs**

---

## Environment Variables

Create a `.env` file in the **project root**:

```dotenv
# ── Application ───────────────────────────────────────────
APP_NAME=LogiScout
APP_VERSION=1.0.0
DEBUG=true
API_V1_PREFIX=/api/v1

# ── CORS ──────────────────────────────────────────────────
ALLOWED_ORIGINS=["*"]

# ── GitHub ────────────────────────────────────────────────
GITHUB_WEBHOOK_SECRET=<your-webhook-secret>

# ── LLM Provider ("gemini" or "groq") ────────────────────
LLM_PROVIDER=groq
GROQ_API_KEY=<your-groq-api-key>
# GEMINI_KEY=<your-gemini-key>

# ── Qdrant ────────────────────────────────────────────────
QDRANT_URL=http://localhost:6333
```

| Variable | Required | Description |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | ✅ | HMAC secret shared with your GitHub webhook |
| `LLM_PROVIDER` | ✅ | `"gemini"` or `"groq"` — must match the API key provided |
| `GROQ_API_KEY` | If groq | Groq API key for LLM diff summarization |
| `GEMINI_KEY` | If gemini | Google Gemini API key |
| `QDRANT_URL` | ❌ | Qdrant connection URL (default: `http://localhost:6333`) |
| `ALLOWED_ORIGINS` | ❌ | CORS allowed origins (JSON array, default: `["*"]`) |

> **Note:** LogiScout currently supports **public repositories only**. No GitHub token is required.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/webhook/{project_id}/github` | Receive GitHub push events for a project |
| `GET` | `/api/v1/commits/timeline` | Latest 5 commits (global, in-memory) |
| `GET` | `/api/v1/commits/{project_id}/timeline` | Latest 5 commits for a specific project |

---

## Commit Ingestion Pipeline

Each commit goes through 5 stages:

```
Webhook Push Event
  │
  ├─ Stage 1: GitHubFetcherService
  │    Calls GitHub API for structured commit data (files, stats)
  │    Fetches .patch diff for raw diff content
  │    Applies diff size cap (4000 chars)
  │
  ├─ Stage 2: DiffAnalyzerService
  │    Classifies change_type (schema_migration, dependency_update, config_change, test, docs)
  │    Classifies risk_level (critical, high, medium, low)
  │    Maps file paths → affected_systems via configurable rules
  │
  ├─ Stage 3: LLMSummarizerService
  │    Multi-provider: Gemini (with model fallback) or Groq
  │    Generates plain-English technical summary
  │    Falls back to raw commit message if LLM fails
  │
  ├─ Stage 4: IndexingPrepService
  │    Builds semantic_text (optimized for embedding quality)
  │    Builds vector_metadata (flat, filterable payload for Qdrant)
  │
  └─ Stage 5: VectorStoreService
       Embeds with BAAI/bge-small-en-v1.5 (384 dimensions)
       Upserts to Qdrant collection: {project_id}_commits
       Deduplication by commit SHA
```

---

## Project Structure

```
Logiscout-Ingestion-Server/
│
├── run.py                              # Starts uvicorn on port 8000
├── requirements.txt
├── .env                                # Environment config (not committed)
│
├── logs/
│   ├── activity.log                    # Rolling commit log (for testing)
│   ├── commits.json                    # In-memory commit state backup
│   └── raw_commit_payloads.json        # Raw webhook payloads backup
│
└── app/
    ├── main.py                         # App factory: lifespan, CORS, router mount
    │
    ├── core/
    │   ├── settings.py                 # Pydantic Settings — loads all env vars
    │   ├── constants.py                # Shared constants
    │   └── logging_config.py           # Logging setup
    │
    ├── api/
    │   ├── router.py                   # Central router — mounts webhook + commits
    │   └── routes/
    │       ├── webhook/
    │       │   └── endpoints.py        # POST /webhook/{project_id}/github
    │       └── commits/
    │           ├── router.py           # Mounts timeline routes under /commits
    │           └── timeline.py         # GET /commits/timeline (global + per-project)
    │
    └── services/
        └── github_webhook_service/
            ├── security.py             # HMAC-SHA256 signature verification
            ├── processor.py            # Bridge: endpoint → v2 pipeline
            ├── state.py                # In-memory rolling window + activity.log
            ├── config.py               # Pipeline configuration (dataclass)
            ├── pipeline.py             # Pipeline orchestrator (5 stages)
            │
            └── pipeline_services/
                ├── models.py           # Pydantic models (RawCommitPayload → CommitDocument)
                ├── github_fetcher.py   # Stage 1: GitHub API + .patch diff
                ├── diff_analyzer.py    # Stage 2: Change type, risk, affected systems
                ├── llm_summarizer.py   # Stage 3: Gemini/Groq LLM summarization
                ├── indexing_prep.py    # Stage 4: Semantic text + vector metadata
                └── vector_store.py     # Stage 5: Embedding + Qdrant upsert
```

---

## Multi-Project Setup

LogiScout supports multiple projects from a single server instance. Each project gets its own Qdrant collection:

```
Project 1234abcd → 1234abcd_commits
Project 7890wxyz → 7890wxyz_commits
```

To add a new project:
1. Create a GitHub webhook on the repo pointing to `https://your-server/api/v1/webhook/{project_id}/github`
2. Use the same `GITHUB_WEBHOOK_SECRET` configured in your `.env`
3. Commits will automatically land in the `{project_id}_commits` Qdrant collection
