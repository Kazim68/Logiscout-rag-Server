"""
Seed Qdrant + ClickHouse with synthetic data for every scenario in scenarios.json.

Idempotent: re-running upserts the same Qdrant points (deterministic UUIDs derived
from scenario_id + correlation_id / commit_sha + suffix) and re-inserts ClickHouse
rows. Noise rows in ClickHouse get deterministic correlationIds keyed by scenario
so re-runs do not balloon the table.

Run from inside the docker container:
    docker exec logiscout-rag-api python -m evaluation.seed_data
"""

from evaluation import env_loader  # noqa: F401  (hydrates os.environ)

import hashlib
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import clickhouse_connect
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


# ── Config ────────────────────────────────────────────────────────────────────

EVAL_PROJECT_ID = os.environ.get("EVAL_PROJECT_ID", "69fcea90cbb613a79de43939")
SCENARIOS_PATH = os.path.join(os.path.dirname(__file__), "scenarios.json")

EMBEDDER = TextEmbedding("BAAI/bge-small-en-v1.5")


# ── Clients ───────────────────────────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    kwargs: Dict[str, Any] = {"url": os.environ["QDRANT_URL"]}
    api_key = os.environ.get("QDRANT_API_KEY") or ""
    if api_key:
        kwargs["api_key"] = api_key
    return QdrantClient(**kwargs)


def get_ch_client():
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", 8123)),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "logging"),
    )


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def ensure_collection(client: QdrantClient, name: str) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        print(f"  + Created collection {name}")


def deterministic_id(*parts: str) -> str:
    """Generate a deterministic UUID for stable upserts."""
    h = hashlib.sha1("|".join(parts).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=h[:16]))


def embed(text: str) -> List[float]:
    return list(EMBEDDER.embed([text]))[0].tolist()


def upsert_trace_doc(client: QdrantClient, project_id: str, doc: dict, point_key: str) -> None:
    collection = f"{project_id}_logs"
    ensure_collection(client, collection)
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=deterministic_id(collection, point_key),
                vector=embed(doc["semantic_text"]),
                payload=doc,
            )
        ],
    )


def upsert_commit_doc(client: QdrantClient, project_id: str, doc: dict, point_key: str) -> None:
    collection = f"{project_id}_commits"
    ensure_collection(client, collection)
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=deterministic_id(collection, point_key),
                vector=embed(doc["semantic_text"]),
                payload=doc,
            )
        ],
    )


# ── ClickHouse helpers ────────────────────────────────────────────────────────

CH_COLUMNS = ["correlationId", "projectId", "timestamp", "level",
              "message", "loggerName", "meta", "exception"]


def insert_log_rows(client, rows: List[dict]) -> None:
    if not rows:
        return
    table = os.environ.get("CLICKHOUSE_LOGS_TABLE", "logs")
    data = [[row[c] for c in CH_COLUMNS] for row in rows]
    client.insert(table, data, column_names=CH_COLUMNS)


def delete_existing_for_project(client, project_id: str) -> None:
    """Wipe rows for this project so reruns stay idempotent."""
    table = os.environ.get("CLICKHOUSE_LOGS_TABLE", "logs")
    try:
        client.command(f"ALTER TABLE {table} DELETE WHERE projectId = %(pid)s",
                       parameters={"pid": project_id})
    except Exception as exc:
        print(f"  [warn] could not pre-clean ClickHouse rows for project: {exc}")


# ── Scenario builders ─────────────────────────────────────────────────────────

INFO_SERVICES = ["api-gateway", "user-service", "frontend", "metrics-collector"]
HEALTHY_PATHS = [
    ("GET", "/api/health"),
    ("GET", "/api/v1/users/{id}"),
    ("POST", "/api/v1/orders/{id}/ack"),
    ("GET", "/api/v1/products"),
    ("GET", "/api/v1/orders"),
    ("PUT", "/api/v1/profile"),
]


def _ts(base_dt: datetime, offset_seconds: int) -> str:
    """Return ISO timestamp with seconds offset, fits ClickHouse DateTime64."""
    return (base_dt + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def build_incident_log_rows(cid: str, scenario: dict, base_dt: datetime) -> List[dict]:
    """3-5 rows per relevant correlationId telling the incident story."""
    rng = random.Random(hashlib.sha1(cid.encode()).hexdigest())
    project_id = scenario["project_id"]
    service = _service_for(scenario)
    title = scenario["title"]
    rc = scenario["ground_truth_root_cause"]

    rows: List[dict] = [
        _row(cid, project_id, _ts(base_dt, 0), "info", service,
             f"Incoming request handling started for incident scenario {scenario['id']}"),
        _row(cid, project_id, _ts(base_dt, 1), "warn", service,
             f"Anomaly detected during {scenario['incident_category']} flow: {title}"),
        _row(cid, project_id, _ts(base_dt, 2), "error", service,
             _error_message(scenario)),
        _row(cid, project_id, _ts(base_dt, 3), "error", service,
             f"Failure detail: {rc[:200]}"),
        _row(cid, project_id, _ts(base_dt, 4), "critical", service,
             f"Request terminated with failure: {scenario['title']}"),
    ]
    return rows


def _service_for(scenario: dict) -> str:
    cat = scenario["incident_category"]
    return {
        "config_drift": "auth-service",
        "dependency_failure": "order-service",
        "code_regression": "checkout-service",
        "resource_exhaustion": "image-service",
        "auth_security": "auth-service",
        "cascade_failure": "api-gateway",
        "schema_migration": "billing-service",
        "race_condition": "inventory-service",
    }.get(cat, "app-service")


def _error_message(scenario: dict) -> str:
    cat = scenario["incident_category"]
    title = scenario["title"]
    canned = {
        "config_drift": f"NullReferenceError reading required env var. Context: {title}",
        "dependency_failure": f"Downstream dependency failed/timed out. Context: {title}",
        "code_regression": f"Regression triggered an unhandled exception. Context: {title}",
        "resource_exhaustion": f"OOM / resource exhausted. Context: {title}",
        "auth_security": f"Token validation failed (signature / key). Context: {title}",
        "cascade_failure": f"Cascading failure across services. Context: {title}",
        "schema_migration": f"DB schema mismatch causing query failure. Context: {title}",
        "race_condition": f"Concurrency conflict / inconsistent state. Context: {title}",
    }
    return canned.get(cat, f"Application error. Context: {title}")


def _row(cid, pid, ts, level, logger_name, message,
         meta="{}", exception="{}") -> dict:
    return {
        "correlationId": cid,
        "projectId": pid,
        "timestamp": ts,
        "level": level,
        "message": message,
        "loggerName": logger_name,
        "meta": meta,
        "exception": exception,
    }


def build_noise_log_rows(project_id: str, scenario_id: str, base_dt: datetime,
                         count: int = 25) -> List[dict]:
    rng = random.Random(scenario_id)
    rows: List[dict] = []
    for i in range(count):
        cid = f"noise-{scenario_id}-{i}"
        method, path = rng.choice(HEALTHY_PATHS)
        service = rng.choice(INFO_SERVICES)
        rows.append(_row(
            cid, project_id, _ts(base_dt, -100 - i * 5), "info", service,
            f"{method} {path} completed successfully in {rng.randint(20, 180)}ms"
        ))
    return rows


def build_trace_doc(cid: str, scenario: dict, base_dt: datetime) -> dict:
    service = _service_for(scenario)
    semantic = (
        f"{scenario['query']}\n"
        f"Flow: {service}\n"
        f"[ERROR] {_error_message(scenario)}\n"
        f"[ERROR] {scenario['ground_truth_root_cause'][:400]}\n"
        f"Outcome: server_error, 500, 312ms\n"
        f"Title: {scenario['title']}"
    )
    return {
        "correlation_id": cid,
        "project_name": "eval-project",
        "project_id": scenario["project_id"],
        "request_method": "POST",
        "request_path": "/api/v1/eval",
        "request_path_pattern": "/api/v1/eval",
        "request_status_code": 500,
        "services": [service],
        "max_level": "error",
        "outcome": "server_error",
        "severity_score": 9,
        "fingerprint": f"TRC-{hashlib.md5(cid.encode()).hexdigest()[:8].upper()}",
        "has_errors": True,
        "has_warnings": True,
        "log_count": 5,
        "levels_present": ["info", "warn", "error", "critical"],
        "environment": "production",
        "duration_ms": 312.0,
        "timestamp_unix": int(base_dt.timestamp()),
        "occurrence_count": 1,
        "last_seen": int(base_dt.timestamp()),
        "semantic_text": semantic,
    }


def build_noise_trace_docs(project_id: str, scenario_id: str, base_dt: datetime,
                           count: int = 12) -> List[dict]:
    rng = random.Random(scenario_id + "-trace")
    docs: List[dict] = []
    for i in range(count):
        method, path = rng.choice(HEALTHY_PATHS)
        service = rng.choice(INFO_SERVICES)
        cid = f"noise-{scenario_id}-trace-{i}"
        semantic = (
            f"{method} {path}.\n"
            f"Flow: {service}\n"
            f"Healthy request. No errors logged.\n"
            f"Outcome: success, 200, {rng.randint(20, 180)}ms"
        )
        docs.append({
            "correlation_id": cid,
            "project_name": "eval-project",
            "project_id": project_id,
            "request_method": method,
            "request_path": path,
            "request_path_pattern": path,
            "request_status_code": 200,
            "services": [service],
            "max_level": "info",
            "outcome": "success",
            "severity_score": 2,
            "fingerprint": f"TRC-{hashlib.md5(cid.encode()).hexdigest()[:8].upper()}",
            "has_errors": False,
            "has_warnings": False,
            "log_count": 3,
            "levels_present": ["info"],
            "environment": "production",
            "duration_ms": float(rng.randint(20, 180)),
            "timestamp_unix": int(base_dt.timestamp()) - (i * 60),
            "occurrence_count": 1,
            "last_seen": int(base_dt.timestamp()) - (i * 60),
            "semantic_text": semantic,
        })
    return docs


def build_commit_doc(sha: str, scenario: dict) -> dict:
    rc = scenario["ground_truth_root_cause"]
    title = scenario["title"]
    cat = scenario["incident_category"]
    change_type = {
        "config_drift": "config_change",
        "schema_migration": "schema_migration",
        "dependency_failure": "dependency_update",
        "auth_security": "config_change",
    }.get(cat, "config_change")
    risk_level = "high" if scenario["difficulty"] == "hard" else "medium"
    semantic = (
        f"Commit {sha}: refactor relating to {title}.\n"
        f"Change explanation: {rc}\n"
        f"This commit is the proximate cause of the incident described."
    )
    service = _service_for(scenario)
    return {
        "commit_sha": sha,
        "repo": "eval-repo",
        "project_id": scenario["project_id"],
        "semantic_text": semantic,
        "author_login": "dev-user",
        "author_name": "Dev User",
        "committed_at": "2024-01-15T08:00:00Z",
        "branch": "main",
        "change_type": change_type,
        "risk_level": risk_level,
        "affected_systems": [service],
        "stats_total": 12,
        "stats_additions": 8,
        "stats_deletions": 4,
        "files_added": [],
        "files_modified": [f"src/{service}/main.py"],
        "files_deleted": [],
        "html_url": f"https://github.com/eval/repo/commit/{sha}",
    }


def build_noise_commit_docs(project_id: str, scenario_id: str,
                            count: int = 6) -> List[dict]:
    rng = random.Random(scenario_id + "-commit")
    docs: List[dict] = []
    trivia = [
        "Updated README with installation steps. No functional changes.",
        "Bumped lint version. Style-only fixes across files.",
        "Added unit tests for utility helpers.",
        "Tweaked log message wording for clarity.",
        "Renamed an internal variable for readability.",
        "Added inline docstrings to existing helpers.",
    ]
    for i in range(count):
        sha = f"noise-{scenario_id}-commit-{i:02x}"
        semantic = trivia[i % len(trivia)]
        docs.append({
            "commit_sha": sha,
            "repo": "eval-repo",
            "project_id": project_id,
            "semantic_text": semantic,
            "author_login": "dev-user",
            "author_name": "Dev User",
            "committed_at": "2024-01-10T08:00:00Z",
            "branch": "main",
            "change_type": "docs" if i % 2 == 0 else "test",
            "risk_level": "low",
            "affected_systems": [],
            "stats_total": 4,
            "stats_additions": 2,
            "stats_deletions": 2,
            "files_added": [],
            "files_modified": ["README.md" if i % 2 == 0 else f"tests/test_{i}.py"],
            "files_deleted": [],
            "html_url": f"https://github.com/eval/repo/commit/{sha}",
        })
    return docs


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    with open(SCENARIOS_PATH) as f:
        scenarios = json.load(f)

    qdrant = get_qdrant_client()
    ch = get_ch_client()

    project_ids_seen = set()

    base_now = datetime.now(timezone.utc).replace(microsecond=0).replace(tzinfo=None)

    for scenario in scenarios:
        project_id = scenario["project_id"]
        if project_id not in project_ids_seen:
            print(f"Cleaning prior eval rows for project_id={project_id} from ClickHouse...")
            delete_existing_for_project(ch, project_id)
            project_ids_seen.add(project_id)

    for idx, scenario in enumerate(scenarios):
        project_id = scenario["project_id"]
        scen_dt = base_now - timedelta(minutes=10 * (len(scenarios) - idx))
        print(f"\n[{idx+1}/{len(scenarios)}] Seeding {scenario['id']} — {scenario['title']}")

        # 1. ClickHouse — relevant log rows
        for cid in scenario["relevant_log_cids"]:
            rows = build_incident_log_rows(cid, scenario, scen_dt)
            insert_log_rows(ch, rows)

        # 2. ClickHouse — noise
        noise_rows = build_noise_log_rows(project_id, scenario["id"], scen_dt, count=25)
        insert_log_rows(ch, noise_rows)

        # 3. Qdrant — relevant TraceDocuments
        for cid in scenario["relevant_log_cids"]:
            doc = build_trace_doc(cid, scenario, scen_dt)
            upsert_trace_doc(qdrant, project_id, doc, point_key=f"{scenario['id']}|{cid}")

        # 4. Qdrant — noise traces
        for noise_doc in build_noise_trace_docs(project_id, scenario["id"], scen_dt, count=12):
            upsert_trace_doc(qdrant, project_id, noise_doc,
                             point_key=f"{scenario['id']}|{noise_doc['correlation_id']}")

        # 5. Qdrant — relevant commits
        for sha in scenario["relevant_commit_shas"]:
            doc = build_commit_doc(sha, scenario)
            upsert_commit_doc(qdrant, project_id, doc, point_key=f"{scenario['id']}|{sha}")

        # 6. Qdrant — noise commits
        for noise_doc in build_noise_commit_docs(project_id, scenario["id"], count=6):
            upsert_commit_doc(qdrant, project_id, noise_doc,
                              point_key=f"{scenario['id']}|{noise_doc['commit_sha']}")

        print(f"  ✓ {scenario['id']} seeded")

    print("\nDone seeding all scenarios.")


if __name__ == "__main__":
    main()
