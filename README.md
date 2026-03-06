# LogiScout — Ingestion Server

A GitHub webhook ingestion server built with **FastAPI** and **Groq LLM**. Receives GitHub push events in real time, summarizes each commit diff using an LLM, and maintains a rolling window of the latest 5 commits in `logs/activity.log`.

---

## How It Works

1. GitHub sends a push event to `POST /api/v1/webhook/github`.
2. The server verifies the HMAC-SHA256 signature.
3. For each commit in the payload, it fetches the diff and sends it to Groq LLM for summarization.
4. The summarized commit is added to an in-memory rolling window (max 5 commits).
5. `logs/activity.log` is rewritten with the latest state after every commit.

> **Next step:** Before being stored in MongoDB, commits will pass through an LLM processing pipeline. The `GET /api/v1/commits/logs` endpoint is ready for that output.

---

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment (see below)

# 4. Start the server
python run.py
```

API docs: **http://localhost:8000/docs**

---

## Environment Variables

Create a `.env` file in the project root:

```dotenv
APP_NAME=LogiScout
APP_VERSION=1.0.0
DEBUG=true
API_V1_PREFIX=/api/v1

MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/
MONGODB_DB_NAME=logiscout

ALLOWED_ORIGINS=["*"]

GITHUB_WEBHOOK_SECRET=<your-webhook-secret>
GITHUB_REPO=<owner>/<repo>
GITHUB_TOKEN=<optional-for-private-repos>

GROQ_API_KEY=gsk_<your-groq-api-key>
```

| Variable | Description |
|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret shared with your GitHub webhook |
| `GITHUB_REPO` | Target repository in `owner/repo` format |
| `GITHUB_TOKEN` | Personal access token (required for private repos) |
| `GROQ_API_KEY` | Groq API key for LLM diff summarization |
| `MONGODB_URL` | MongoDB/Atlas connection string |
| `MONGODB_DB_NAME` | Database name |
| `ALLOWED_ORIGINS` | CORS allowed origins (JSON array) |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/webhook/github` | Receive GitHub push events |
| `GET` | `/api/v1/commits/timeline` | Latest 5 commits (in-memory, live) |
| `GET` | `/api/v1/commits/logs` | LLM-processed commits from MongoDB (future) |

---

## Project Structure

```
Logiscout-Ingestion-Server/
│
├── run.py                         # Starts uvicorn on port 8000
├── requirements.txt
├── .env                           # Environment config (not committed)
│
├── logs/
│   └── activity.log               # Rolling commit log — rewritten on every webhook
│
└── app/
    ├── main.py                    # App factory: lifespan (DB init), CORS, router mount
    │
    ├── core/
    │   ├── settings.py            # Pydantic Settings — loads all env vars
    │   ├── constants.py           # Shared constants (MongoDB collection names)
    │   └── logging_config.py      # Logging setup
    │
    ├── api/
    │   ├── router.py              # Central router — mounts webhook + commits routes
    │   └── routes/
    │       ├── webhook/
    │       │   └── endpoints.py   # POST /webhook/github — signature verify + dispatch
    │       └── commits/
    │           ├── router.py      # Mounts timeline + logs under /commits
    │           ├── timeline.py    # GET /commits/timeline — in-memory rolling window
    │           └── logs.py        # GET /commits/logs — processed commits from MongoDB
    │
    ├── services/
    │   └── github_webhook_service/
    │       ├── processor.py       # Extracts commits, fetches diffs, calls Groq, calls add_commit
    │       ├── groq_client.py     # Groq LLM client — summarizes raw Git diffs
    │       ├── state.py           # In-memory deque (max 5) + activity.log writer
    │       └── security.py        # HMAC-SHA256 signature verification
    │
    └── db/
        └── mongodb/
            └── database.py        # Motor async client — init, close, get_db
```

