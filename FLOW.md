# LogiScout — Complete Server Flow & Architecture

> **LogiScout** is an intelligent log ingestion & analytics platform built with FastAPI, MongoDB Atlas, and Groq LLM integration. It features GitHub webhook processing, periodic commit syncing via cron, and LLM-powered diff summarization.

---

## Table of Contents

1. [Running the Server](#running-the-server)
2. [Project Structure](#project-structure)
3. [Server Startup Flow](#server-startup-flow)
4. [Complete Data Flow](#complete-data-flow)
5. [API Endpoints](#api-endpoints)
6. [GitHub Webhook Flow](#github-webhook-flow)
7. [Cron Job Flow](#cron-job-flow)
8. [Activity Log](#activity-log)
9. [Database Schema](#database-schema)
10. [Configuration](#configuration)
11. [Architecture Diagram](#architecture-diagram)

---

## Running the Server

### Prerequisites

- Python 3.10+
- MongoDB Atlas account (or local MongoDB)
- GitHub repository for webhook integration
- Groq API key (for LLM summarization)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Set Up Environment

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

### Start the Server

```bash
python run.py
```

This starts the FastAPI server with **uvicorn** on `http://0.0.0.0:8000` with hot-reload enabled.

| Parameter | Value |
|-----------|-------|
| Host | `0.0.0.0` |
| Port | `8000` |
| Reload | `True` (auto-restart on code changes) |
| Log Level | `info` |

**Alternative command (without run.py):**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Access Points

| URL | Description |
|-----|-------------|
| `http://localhost:8000/docs` | Swagger UI (interactive API docs) |
| `http://localhost:8000/redoc` | ReDoc (alternative API docs) |
| `http://localhost:8000/health` | Health check endpoint |
| `http://localhost:8000/ready` | Readiness probe |

---

## Project Structure

```
Ingestion-server/
├── run.py                          # Entry point – starts uvicorn
├── requirements.txt                # Python dependencies
├── .env                            # Environment variables (not committed)
├── logs/
│   └── activity.log                # Auto-generated commit activity log
│
└── app/
    ├── main.py                     # FastAPI app factory + lifespan hooks
    │
    ├── core/
    │   ├── settings.py             # Pydantic Settings (reads .env)
    │   ├── logging_config.py       # Structured logging setup
    │   ├── constants.py            # App-wide constants
    │   └── security.py             # Auth utilities (JWT, etc.)
    │
    ├── api/
    │   ├── router.py               # Central router – aggregates all routes
    │   └── routes/
    │       ├── health/
    │       │   └── endpoints.py    # GET /health, GET /ready
    │       ├── ingestion/
    │       │   └── endpoints.py    # POST /api/v1/ingestion/
    │       ├── webhook/
    │       │   └── endpoints.py    # POST /api/v1/webhook/github
    │       └── analytics/
    │           └── endpoints.py    # GET /api/v1/analytics/github-commits
    │
    ├── db/
    │   ├── postgres/
    │   │   └── database.py         # MongoDB connection (Motor async driver)
    │   ├── olap/
    │   │   └── connector.py        # ClickHouse connector (placeholder)
    │   └── migrations/
    │       └── README.md
    │
    ├── services/
    │   ├── github_webhook_service/
    │   │   ├── processor.py        # Process GitHub push events
    │   │   ├── state.py            # MongoDB persistence + activity.log
    │   │   ├── github_client.py    # GitHub API – fetch commits
    │   │   ├── groq_client.py      # Groq LLM – diff summarization
    │   │   └── security.py         # HMAC-SHA256 signature verification
    │   ├── ingestion_service/      # (placeholder)
    │   ├── analytics_service/      # (placeholder)
    │   ├── storage_service/        # (placeholder)
    │   ├── vector_service/         # (placeholder)
    │   └── ...
    │
    ├── cron/
    │   ├── jobs/
    │   │   └── cleanup.py          # GitHub sync cron job
    │   └── scheduler/
    │       └── scheduler.py        # APScheduler setup (5-min interval)
    │
    ├── kafka/                      # Kafka consumers/producers (placeholder)
    ├── workers/                    # Background workers (placeholder)
    └── utils/
        └── helpers.py              # Utility functions
```

---

## Server Startup Flow

When you run `python run.py`, the following sequence executes:

```
run.py
  └── uvicorn.run("app.main:app")
        └── FastAPI lifespan(app) starts
              │
              ├── 1. setup_logging()
              │       → Configures structured logging to stdout
              │
              ├── 2. await init_db()
              │       → Creates Motor (async MongoDB) client
              │       → Pings MongoDB Atlas to verify connection
              │       → Logs: "MongoDB connected → logiscout-ingestion"
              │
              ├── 3. GitHub Commits Initialization
              │       → fetch_recent_commits(count=5)
              │       │   → GET https://api.github.com/repos/{owner}/{repo}/commits?per_page=5
              │       │   → For each commit:
              │       │       → Fetch diff via GitHub API (.patch format)
              │       │       → Send diff to Groq LLM (llama-3.1-8b-instant)
              │       │       → Receive AI-generated summary
              │       │       → Build entry dict with all fields
              │       │
              │       → await sync_commits(commits)
              │       │   → Clear existing documents from github_commits collection
              │       │   → Insert all 5 commits into MongoDB
              │       │   → Rewrite logs/activity.log with full JSON timeline
              │       │
              │       → Logs: "✅ Initialized with 5 commits from GitHub"
              │
              ├── 4. start_scheduler()
              │       → Creates BackgroundScheduler(daemon=True)
              │       → Adds job: run_sync_job every 5 minutes
              │       → Logs: "✅ Cron scheduler started successfully"
              │
              └── 5. Server is now listening on http://0.0.0.0:8000
                      → Swagger docs at /docs
                      → Health check at /health

              ─── ON SHUTDOWN ───
              │
              ├── stop_scheduler() → Stops APScheduler
              └── await close_db() → Closes MongoDB connection
```

---

## Complete Data Flow

### Flow 1: Server Startup → GitHub API → MongoDB → Activity Log

```
[Server Starts]
    │
    ▼
[GitHub API] ──GET /repos/{repo}/commits──► [5 commits returned]
    │
    ▼ (for each commit)
[GitHub API] ──GET /repos/{repo}/commits/{sha} (.patch)──► [diff text]
    │
    ▼
[Groq LLM API] ──POST /chat/completions──► [AI summary of diff]
    │
    ▼
[Build Entry Dict]
    {
      "source": "github_api",
      "repo": "owner/repo",
      "commit": "abc1234",
      "full_sha": "abc1234567890...",
      "message": "fix: update login flow",
      "author": "John Doe",
      "pusher": "API Fetch",
      "branch": "main",
      "timestamp": "2025-03-05T10:30:00Z",
      "summary": "This commit modifies the login..."
    }
    │
    ▼
[MongoDB] ──INSERT INTO github_commits──► [5 documents stored]
    │
    ▼
[logs/activity.log] ──REWRITE──► [Full JSON timeline written]
```

### Flow 2: GitHub Webhook → Process → MongoDB → Activity Log

```
[GitHub Push Event]
    │
    ▼
POST /api/v1/webhook/github
    │
    ├── Read raw body
    ├── Verify HMAC-SHA256 signature (X-Hub-Signature-256)
    ├── Parse JSON payload
    │
    ▼
[processor.py] process_push_event(payload)
    │
    ├── Extract: repo, branch, pusher
    ├── For each commit in payload:
    │   ├── Fetch diff (commit_url + .patch)
    │   ├── Send to Groq LLM → get summary
    │   ├── Build entry dict
    │   └── await add_commit(entry)
    │       │
    │       ├── Check for duplicate (by full_sha)
    │       ├── INSERT into MongoDB github_commits
    │       ├── If total > 5: DELETE oldest commit(s)
    │       └── REWRITE logs/activity.log
    │
    ▼
Response: { "status": "processed", "commits": N }
```

### Flow 3: Cron Job → GitHub API → MongoDB → Activity Log

```
[Every 5 minutes – APScheduler]
    │
    ▼
run_sync_job() → asyncio.run(sync_github_commits_job())
    │
    ├── fetch_recent_commits(count=5) → [same as Flow 1]
    │
    ▼
await sync_commits(commits)
    │
    ├── DELETE ALL from github_commits collection
    ├── INSERT 5 fresh commits
    └── REWRITE logs/activity.log
```

---

## API Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe – returns app name & version |
| `GET` | `/ready` | Readiness probe |

### Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/ingestion/` | Submit raw data for ingestion pipeline |
| `GET` | `/api/v1/ingestion/{job_id}` | Check ingestion job status |

**POST body:**
```json
{
  "source": "github",
  "payload": { "any": "data" },
  "metadata": {}
}
```

### Webhook

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/webhook/github` | Receive GitHub push events |

**Required Header:** `X-Hub-Signature-256: sha256=<hmac_hex>`

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/analytics/github-commits` | Get latest 5 commits from DB |
| `GET` | `/api/v1/analytics/logs` | Query processed logs (supports `source`, `limit`, `skip`) |
| `GET` | `/api/v1/analytics/summary` | Analytics summary (placeholder) |

**GET /api/v1/analytics/github-commits response:**
```json
{
  "total": 5,
  "max_commits": 5,
  "commits": [
    {
      "source": "github_api",
      "repo": "Sami-153/todo-app",
      "commit": "abc1234",
      "full_sha": "abc1234567890abcdef...",
      "message": "fix: update login flow",
      "author": "Sami",
      "pusher": "API Fetch",
      "branch": "main",
      "timestamp": "2025-03-05T10:30:00Z",
      "summary": "This commit modifies..."
    }
  ],
  "note": "Timeline syncs every 5 minutes via cron job"
}
```

---

## GitHub Webhook Flow

### Setup (on GitHub)

1. Go to your repo → **Settings** → **Webhooks** → **Add webhook**
2. **Payload URL:** `https://<your-server>/api/v1/webhook/github`
3. **Content type:** `application/json`
4. **Secret:** Same value as `GITHUB_WEBHOOK_SECRET` in `.env`
5. **Events:** Select "Just the push event"

### Processing Steps

```
1. GitHub sends POST request with:
   ├── Header: X-Hub-Signature-256 = sha256=<HMAC of body>
   ├── Header: X-GitHub-Event = push
   └── Body: JSON payload with commits array

2. Server receives at POST /api/v1/webhook/github
   ├── Reads raw body bytes
   ├── Computes HMAC-SHA256(body, GITHUB_WEBHOOK_SECRET)
   └── Compares with X-Hub-Signature-256 header (timing-safe)

3. If signature valid and event == "push":
   ├── Extract repo name, branch, pusher
   ├── For each commit:
   │   ├── Fetch .patch diff from GitHub
   │   ├── Send diff to Groq API (llama-3.1-8b-instant)
   │   ├── Get AI-generated summary
   │   └── Store in MongoDB (add_commit)
   └── Maintain rolling window of 5 commits

4. Response: { "status": "processed", "commits": N }
```

### Signature Verification (security.py)

```python
mac = hmac.new(
    GITHUB_WEBHOOK_SECRET.encode(),
    msg=raw_body,
    digestmod=hashlib.sha256
)
expected = "sha256=" + mac.hexdigest()
# Timing-safe comparison
hmac.compare_digest(expected, received_signature)
```

---

## Cron Job Flow

The server uses **APScheduler** (`BackgroundScheduler`) to periodically sync GitHub commits.

### Schedule

| Property | Value |
|----------|-------|
| Trigger | `IntervalTrigger(minutes=5)` |
| Job ID | `github_commits_sync` |
| Max Instances | `1` (prevents overlap) |
| Daemon | `True` (won't block shutdown) |

### Execution Chain

```
APScheduler timer fires (every 5 min)
    │
    ▼
run_sync_job()                          [cron/jobs/cleanup.py]
    │ (asyncio.run wrapper)
    ▼
sync_github_commits_job()               [async]
    │
    ├── fetch_recent_commits(count=5)   [github_client.py]
    │   ├── GET GitHub API /commits
    │   ├── For each: fetch diff + LLM summarize
    │   └── Return list of 5 entry dicts
    │
    └── sync_commits(commits)           [state.py]
        ├── DELETE ALL from github_commits
        ├── INSERT 5 new commits
        └── REWRITE logs/activity.log
```

---

## Activity Log

The file `logs/activity.log` is **completely rewritten** on every change (startup sync, webhook push, cron sync). It always reflects the current state of the database.

### Format

```
======================================================================
  LOGISCOUT — GitHub Commit Activity Log
  Last Updated: 2025-03-05T15:30:00.123456
  Total Commits: 5 / 5
======================================================================

[2025-03-05T15:30:00.123456] ✅ NEW COMMIT ADDED:
{
  "source": "github_webhook",
  "repo": "Sami-153/todo-app",
  "commit": "abc1234",
  "full_sha": "abc1234567890abcdef...",
  "message": "fix: update login flow",
  "author": "Sami",
  "pusher": "Sami",
  "branch": "main",
  "timestamp": "2025-03-05T15:29:50Z",
  "summary": "This commit modifies the authentication..."
}

----------------------------------------------------------------------
  CURRENT TIMELINE (5 commits, newest first)
----------------------------------------------------------------------

  [1] abc1234 — fix: update login flow
{
    "source": "github_webhook",
    "repo": "Sami-153/todo-app",
    "commit": "abc1234",
    ...
}

  [2] def5678 — feat: add dashboard
{
    ...
}

  ... (up to 5 commits)

======================================================================
```

### Entry Fields

Every commit entry contains these 10 fields:

| Field | Description | Example |
|-------|-------------|---------|
| `source` | Origin of the commit data | `"github_api"` or `"github_webhook"` |
| `repo` | Repository full name | `"Sami-153/todo-app"` |
| `commit` | Short SHA (7 chars) | `"abc1234"` |
| `full_sha` | Full commit SHA | `"abc1234567890..."` |
| `message` | Commit message (first line) | `"fix: update login"` |
| `author` | Commit author name | `"Sami"` |
| `pusher` | Who pushed (webhook) or "API Fetch" (cron) | `"Sami"` |
| `branch` | Branch name | `"main"` |
| `timestamp` | Commit timestamp (ISO 8601) | `"2025-03-05T15:30:00Z"` |
| `summary` | AI-generated diff summary from Groq LLM | `"This commit modifies..."` |

---

## Database Schema

### MongoDB Database: `logiscout-ingestion`

#### Collection: `github_commits`

Stores the rolling window of 5 most recent commits.

```json
{
  "_id": ObjectId("..."),
  "source": "github_api",
  "repo": "Sami-153/todo-app",
  "commit": "abc1234",
  "full_sha": "abc1234567890abcdef1234567890abcdef123456",
  "message": "fix: update login flow",
  "author": "Sami",
  "pusher": "API Fetch",
  "branch": "main",
  "timestamp": "2025-03-05T10:30:00Z",
  "summary": "This commit updates the login authentication...",
  "created_at": ISODate("2025-03-05T15:30:00.000Z"),
  "updated_at": ISODate("2025-03-05T15:30:00.000Z")
}
```

**Rolling Window Rule:** Maximum 5 documents. When a new commit is added via webhook and total exceeds 5, the oldest commit(s) are automatically deleted.

#### Collection: `ingestion_jobs`

Stores ingestion pipeline jobs.

```json
{
  "_id": ObjectId("..."),
  "source": "github",
  "payload": { ... },
  "metadata": {},
  "status": "pending",
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

---

## Configuration

All configuration is loaded from `.env` via **pydantic-settings** (`app/core/settings.py`).

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB Atlas connection string | `mongodb+srv://user:pass@cluster.mongodb.net/` |
| `MONGODB_DB_NAME` | Database name | `logiscout-ingestion` |
| `GITHUB_WEBHOOK_SECRET` | Secret for webhook signature verification | `mysecret123` |
| `GITHUB_REPO` | Target repository (owner/repo format) | `Sami-153/todo-app` |
| `GROQ_API_KEY` | Groq API key for LLM summarization | `gsk_...` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `LogiScout` | Application name |
| `APP_VERSION` | `0.1.0` | Version string |
| `DEBUG` | `false` | Enable debug logging |
| `API_V1_PREFIX` | `/api/v1` | API version prefix |
| `ALLOWED_ORIGINS` | `["*"]` | CORS allowed origins |
| `CRON_ENABLED` | `true` | Enable/disable cron scheduler |
| `GITHUB_TOKEN` | `None` | GitHub token (for private repos) |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        LogiScout Server                         │
│                     (FastAPI + Uvicorn)                          │
│                   http://0.0.0.0:8000                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  │
│  │  /health │  │ /api/v1/     │  │ /api/v1/ │  │ /api/v1/   │  │
│  │  /ready  │  │ ingestion/   │  │ webhook/ │  │ analytics/ │  │
│  └──────────┘  └──────┬───────┘  └─────┬────┘  └─────┬──────┘  │
│                       │                │              │         │
│                       ▼                ▼              ▼         │
│              ┌────────────────────────────────────────────┐     │
│              │            Services Layer                  │     │
│              │                                            │     │
│              │  ┌──────────────────────────────────────┐  │     │
│              │  │     github_webhook_service            │  │     │
│              │  │                                      │  │     │
│              │  │  ┌────────────┐  ┌───────────────┐   │  │     │
│              │  │  │ processor  │  │ github_client │   │  │     │
│              │  │  └─────┬──────┘  └───────┬───────┘   │  │     │
│              │  │        │                 │            │  │     │
│              │  │        ▼                 ▼            │  │     │
│              │  │  ┌────────────┐  ┌───────────────┐   │  │     │
│              │  │  │ groq_client│  │   security    │   │  │     │
│              │  │  │ (LLM API) │  │ (HMAC verify) │   │  │     │
│              │  │  └─────┬──────┘  └───────────────┘   │  │     │
│              │  │        │                              │  │     │
│              │  │        ▼                              │  │     │
│              │  │  ┌────────────┐                       │  │     │
│              │  │  │   state    │──► logs/activity.log  │  │     │
│              │  │  │ (MongoDB)  │                       │  │     │
│              │  │  └────────────┘                       │  │     │
│              │  └──────────────────────────────────────┘  │     │
│              └────────────────────────────────────────────┘     │
│                                                                 │
│  ┌──────────────────────┐                                       │
│  │   Cron Scheduler     │                                       │
│  │   (APScheduler)      │                                       │
│  │   Every 5 minutes    │──► fetch_recent_commits()             │
│  │                      │──► sync_commits() → MongoDB           │
│  └──────────────────────┘                                       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                    External Services                            │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │  MongoDB     │  │  GitHub API  │  │  Groq LLM API       │   │
│  │  Atlas       │  │              │  │  (llama-3.1-8b)     │   │
│  │              │  │  Commits     │  │                     │   │
│  │  github_     │  │  Diffs       │  │  Diff summaries     │   │
│  │  commits     │  │  Webhooks    │  │                     │   │
│  └──────────────┘  └──────────────┘  └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference

| Action | Command / URL |
|--------|---------------|
| Start server | `python run.py` |
| Swagger docs | `http://localhost:8000/docs` |
| Health check | `GET http://localhost:8000/health` |
| View commits | `GET http://localhost:8000/api/v1/analytics/github-commits` |
| Activity log | Open `logs/activity.log` |
| Cron interval | Every 5 minutes (configurable in `scheduler.py`) |
| Max commits | 5 (configurable in `state.py → MAX_COMMITS`) |
