"""
Calls the live LogiScout RAG server and parses the NDJSON stream emitted by
POST /api/v1/response.

Stream contract (verified against pipeline.py):
    {"event": "status",  "data": {"stage": "..."}}
    {"event": "intent",  "data": {"intent": str, "needs_logs": bool, ...}}
    {"event": "status",  "data": {"stage": "retrieval"}}
    {"event": "answer",  "data": {"text": str, "log_context": [...], "commit_context": [...], ...}}
    {"event": "done",    "data": {"ok": bool, "sources": [...]}}
    {"event": "error",   "data": {...}}   (on failure)

Each entry in log_context/commit_context is shaped as:
    {"id": str, "score": float, "semantic_text": str, "metadata": {<full payload>}}

So retrieved correlation_ids and commit_shas are pulled from `metadata` of
each item in log_context / commit_context inside the `answer` event.
"""
from evaluation import env_loader  # noqa: F401

import json
import os
import time
from typing import Any, Dict, List

import httpx


RAG_SERVER_URL = os.environ.get("RAG_SERVER_URL", "http://localhost:9000")


def _items(value: Any) -> List[dict]:
    if not value:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def run_logiscout_pipeline(scenario: dict, timeout_seconds: int = 180) -> Dict[str, Any]:
    """Run a single scenario through the live RAG server and capture the result."""
    payload = {
        "project_id": scenario["project_id"],
        "user_prompt": scenario["query"],
        "chat_context": [],
        "vague_context": "",
    }

    result: Dict[str, Any] = {
        "intent": None,
        "needs_logs": False,
        "needs_commits": False,
        "needs_postmortem": False,
        "answer": "",
        "retrieved_log_cids": [],
        "retrieved_commit_shas": [],
        "retrieved_log_contexts": [],
        "retrieved_commit_contexts": [],
        "retrieved_contexts_raw": [],
        "latency_seconds": 0.0,
        "error": None,
        "ok": False,
        "sources": [],
        "provider": None,
    }

    start = time.time()

    try:
        with httpx.stream(
            "POST",
            f"{RAG_SERVER_URL}/api/v1/response",
            json=payload,
            timeout=timeout_seconds,
            headers={"Accept": "application/x-ndjson"},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("event")
                data = event.get("data") or {}

                if etype == "intent":
                    result["intent"] = data.get("intent")
                    result["needs_logs"] = bool(data.get("needs_logs"))
                    result["needs_commits"] = bool(data.get("needs_commits"))
                    result["needs_postmortem"] = bool(data.get("needs_postmortem"))

                elif etype == "answer":
                    chunk = data.get("text") or data.get("content") or ""
                    if chunk:
                        result["answer"] += chunk
                    result["provider"] = data.get("provider") or result["provider"]

                    log_ctx = _items(data.get("log_context"))
                    commit_ctx = _items(data.get("commit_context"))

                    if log_ctx:
                        result["retrieved_log_contexts"] = log_ctx
                        for item in log_ctx:
                            md = item.get("metadata") or {}
                            cid = md.get("correlation_id") or md.get("correlationId")
                            if cid:
                                result["retrieved_log_cids"].append(cid)

                    if commit_ctx:
                        result["retrieved_commit_contexts"] = commit_ctx
                        for item in commit_ctx:
                            md = item.get("metadata") or {}
                            sha = md.get("commit_sha") or md.get("sha")
                            if sha:
                                result["retrieved_commit_shas"].append(sha)

                    result["retrieved_contexts_raw"] = log_ctx + commit_ctx

                elif etype == "done":
                    result["ok"] = bool(data.get("ok"))
                    result["sources"] = data.get("sources") or []

                elif etype == "error":
                    result["error"] = data.get("message") or json.dumps(data)

    except Exception as e:
        result["error"] = str(e)
        print(f"  [Pipeline] Error calling RAG server: {e}")

    result["latency_seconds"] = round(time.time() - start, 2)
    return result
