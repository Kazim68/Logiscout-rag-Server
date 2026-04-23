"""Fetch the most recent commits from the GitHub REST API on startup.

This module is called once during server lifespan to pre-populate the
rolling commit window so the timeline is never empty.
"""

import json
import logging

import httpx

from app.core.settings import settings
from app.services.github_webhook_service.groq_client import summarize_diff
from app.services.github_webhook_service.state import (
    COMMITS_FILE_PATH,
    add_commit,
    add_raw_payload,
    write_activity_log,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DIFF_TIMEOUT = 15
API_TIMEOUT = 20
USER_AGENT = "LogiScout-Webhook-Agent"


async def fetch_and_populate_commits() -> None:
    """Fetch last 5 commits from GitHub and seed commits + raw payloads.

    Skips entirely when commits.json already contains data (idempotent
    across server restarts).
    """
    # ── Guard: already populated? ────────────────────────────
    if COMMITS_FILE_PATH.exists():
        try:
            data = json.loads(COMMITS_FILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                logger.info(
                    "Commits file already has %d entries — skipping API fetch",
                    len(data),
                )
                await write_activity_log()
                return
        except (json.JSONDecodeError, OSError):
            pass  # corrupt / unreadable — proceed with fetch

    # ── Guard: repo configured? ──────────────────────────────
    if not settings.GITHUB_REPO:
        logger.warning("GITHUB_REPO not set — cannot pre-populate commits")
        return

    repo = settings.GITHUB_REPO  # e.g. "Sami-153/todo-app"
    logger.info("Pre-populating commits from GitHub API for %s …", repo)

    # ── Fetch commit list ────────────────────────────────────
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": USER_AGENT,
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{repo}/commits",
                params={"per_page": 5, "sha": "main"},
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error(
                "GitHub API returned %d: %s", resp.status_code, resp.text[:300]
            )
            return

        commits_list = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch commits from GitHub API: %s", exc)
        return

    if not isinstance(commits_list, list) or not commits_list:
        logger.warning("GitHub API returned empty or invalid commits list")
        return

    # ── Process oldest-first so deque ends up newest-first ───
    for commit_obj in reversed(commits_list):
        try:
            sha = commit_obj["sha"]
            html_url = commit_obj["html_url"]
            commit_data = commit_obj["commit"]
            message = commit_data["message"]
            author_name = commit_data["author"]["name"]
            timestamp = commit_data["author"]["date"]
            committer_login = (commit_obj.get("author") or {}).get("login", "unknown")

            logger.info("Fetching diff for %s …", sha[:7])

            # Fetch .patch diff
            try:
                async with httpx.AsyncClient(timeout=DIFF_TIMEOUT) as client:
                    diff_resp = await client.get(
                        f"{html_url}.patch",
                        headers={
                            "Accept": "application/vnd.github.v3.patch",
                            "User-Agent": USER_AGENT,
                        },
                    )
                if diff_resp.status_code != 200 or not diff_resp.text.strip():
                    summary = "No diff available for this commit."
                else:
                    summary = await summarize_diff(diff_resp.text)
            except Exception as e:
                logger.error("Error fetching diff for %s: %s", sha[:7], e)
                summary = f"Error fetching diff: {e}"

            # Build commit entry (same format as webhook flow)
            entry = {
                "source": "github_api",
                "repo": repo,
                "commit": sha[:7],
                "full_sha": sha,
                "message": message,
                "author": author_name,
                "pusher": "API Fetch",
                "branch": "main",
                "timestamp": timestamp,
                "summary": summary,
            }

            # Store the full GitHub API commit object as raw payload
            await add_raw_payload(commit_obj)
            await add_commit(entry)

        except Exception as exc:
            logger.error("Error processing API commit %s: %s", commit_obj.get("sha", "?")[:7], exc)
            continue

    logger.info("Pre-populated %d commit(s) from GitHub API", len(commits_list))

    # Ensure activity.log is written after bulk insert
    await write_activity_log()
