# LogiScout

Intelligent log ingestion and analytics platform built with **FastAPI**, **MongoDB Atlas**, and **Groq LLM** integration. Features GitHub webhook processing, periodic commit syncing via cron, and AI-powered diff summarization.

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\Activate.ps1   # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
python run.py
```

The API docs will be available at **http://localhost:8000/docs**.

---

## Environment Variables

Create a `.env` file in the project root:

```dotenv
APP_NAME=LogiScout
APP_VERSION=1.0.0
DEBUG=true
API_V1_PREFIX=/api/v1

MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=<app>
MONGODB_DB_NAME=logiscout-ingestion

ALLOWED_ORIGINS=["*"]

GITHUB_WEBHOOK_SECRET=<your-webhook-secret>
GITHUB_REPO=<owner>/<repo>

GROQ_API_KEY=gsk_<your-groq-api-key>
```

| Variable | Description |
|---|---|
| `MONGODB_URL` | MongoDB/Atlas connection string |
| `MONGODB_DB_NAME` | Database name for all collections |
| `ALLOWED_ORIGINS` | CORS allowed origins (JSON array) |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret shared with GitHub webhook config |
| `GITHUB_REPO` | Target repo in `owner/repo` format |
| `GROQ_API_KEY` | API key for Groq LLM diff summarization |
| `DEBUG` | Enable debug mode (`true`/`false`) |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe — returns app name & version |
| `GET` | `/ready` | Readiness probe |
| `POST` | `/api/v1/ingestion/` | Submit raw data for the ingestion pipeline |
| `GET` | `/api/v1/ingestion/{job_id}` | Check ingestion job status |
| `POST` | `/api/v1/webhook/github` | Receive & process GitHub push events |
| `GET` | `/api/v1/analytics/github-commits` | Get the latest 5 commits from the DB |
| `GET` | `/api/v1/analytics/logs` | Query processed logs (supports `source`, `limit`, `skip`) |
| `GET` | `/api/v1/analytics/summary` | Analytics summary (placeholder) |

---

## Project Structure — File-by-File

```
Ingestion-server/
│
├── run.py                     # Entry point — starts uvicorn dev server on port 8000
├── requirements.txt           # All Python dependencies (FastAPI, Motor, APScheduler, etc.)
├── README.md                  # This file
├── FLOW.md                    # Detailed architecture, data-flow diagrams, and sequence docs
│
├── logs/
│   └── activity.log           # Auto-generated commit activity log (rewritten on every sync)
│
└── app/                       # Main application package
    ├── __init__.py
    ├── main.py                # FastAPI app factory — lifespan hooks (DB init, scheduler start,
    │                          #   GitHub commit bootstrap), CORS, exception handlers, router mount
    │
    ├── core/                  # Application-wide configuration & utilities
    │   ├── settings.py        # Pydantic Settings — loads every env var from .env
    │   ├── constants.py       # Shared constants: MongoDB collection names, Kafka topics, job statuses
    │   └── logging_config.py  # Structured logging setup; silences noisy third-party loggers
    │
    ├── api/                   # HTTP layer — all routes live here
    │   ├── router.py          # Central APIRouter — aggregates and mounts every route module
    │   └── routes/
    │       ├── health/
    │       │   └── endpoints.py    # GET /health & GET /ready — liveness & readiness probes
    │       ├── ingestion/
    │       │   └── endpoints.py    # POST /ingestion/ — accepts payloads, stores as jobs in MongoDB
    │       │                       # GET  /ingestion/{job_id} — poll job status
    │       ├── webhook/
    │       │   └── endpoints.py    # POST /webhook/github — receives GitHub push events,
    │       │                       #   verifies HMAC signature, delegates to processor
    │       └── analytics/
    │           └── endpoints.py    # GET /analytics/github-commits — returns latest 5 commits
    │                               # GET /analytics/logs — query processed logs
    │                               # GET /analytics/summary — placeholder aggregation
    │
    ├── services/              # Business logic layer
    │   └── github_webhook_service/
    │       ├── processor.py   # Orchestrates push-event handling: extracts commits, fetches diffs,
    │       │                  #   calls LLM for summaries, persists to DB
    │       ├── github_client.py  # GitHub REST API client — fetches commits list & .patch diffs
    │       ├── groq_client.py    # Groq LLM client — sends diffs to llama-3.1-8b-instant, returns
    │       │                     #   AI-generated summaries
    │       ├── state.py       # MongoDB-backed state manager — add/sync commits, maintain a rolling
    │       │                  #   5-commit window, rewrite logs/activity.log on every change
    │       └── security.py    # HMAC-SHA256 signature verification for incoming GitHub webhooks
    │
    ├── cron/                  # Scheduled background jobs
    │   ├── jobs/
    │   │   └── cleanup.py     # Cron job function — fetches latest 5 GitHub commits, syncs to DB
    │   └── scheduler/
    │       └── scheduler.py   # APScheduler BackgroundScheduler — runs the sync job every 5 minutes
    │
    ├── kafka/                 # Kafka integration (stubs — ready for implementation)
    │   ├── producers/
    │   │   └── ingestion_producer.py  # Producer stub — publishes messages to ingestion topics
    │   ├── consumers/
    │   │   └── ingestion_consumer.py  # Consumer stub — subscribes to topics, routes to pipeline
    │   └── schemas/
    │       └── messages.py    # Pydantic model defining the Kafka ingestion message schema
    │
    ├── db/                    # Database connectors
    │   └── mongodb/
    │       └── database.py    # Motor async MongoDB client — init, close, and get-db helpers
    │
    ├── workers/               # Background worker processes (stubs — ready for implementation)
    │   ├── cron_worker/
    │   │   └── worker.py      # Standalone process for running scheduled cron tasks
    │   ├── ingestion_worker/
    │   │   └── worker.py      # Standalone process for heavy ingestion processing
    │   └── kafka_worker/
    │       └── worker.py      # Standalone process for Kafka consume → LLM pipeline
    │
    └── utils/
        └── helpers.py         # Shared utility: returns current UTC timestamp
```

---

## How It Works (Brief)

1. **Startup** — `run.py` launches uvicorn which loads `app/main.py`. The lifespan hook connects to MongoDB, fetches the 5 most recent GitHub commits (with LLM-summarized diffs via Groq), stores them, and starts a 5-minute cron scheduler.

2. **Webhook path** — When a push happens on GitHub, a POST hits `/api/v1/webhook/github`. The server verifies the HMAC-SHA256 signature, extracts each commit, fetches its diff, summarizes it with Groq, and upserts into MongoDB while keeping a rolling window of 5 commits.

3. **Cron path** — Every 5 minutes APScheduler fires `cleanup.py`, which re-fetches the latest 5 commits from the GitHub API, re-summarizes, and replaces the DB contents.

4. **Analytics** — The `/analytics/github-commits` endpoint reads the 5 stored commits from MongoDB and returns them. Additional log querying is available via `/analytics/logs`.

5. **Activity log** — Every sync (startup, webhook, cron) rewrites `logs/activity.log` with a formatted timeline of all stored commits.
