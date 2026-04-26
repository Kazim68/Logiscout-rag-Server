"""GitHub Fetcher Service: Calls GitHub API and fetches .patch diff for a commit."""

import logging
from typing import Optional

import requests

from .models import FetchedCommitDetail, FetchedFileDetail

logger = logging.getLogger(__name__)

# Reused from OLD_GITHUB_PIPELINE/processor.py
USER_AGENT = "LogiScout-Webhook-Agent"
GITHUB_DIFF_TIMEOUT = 15


class GitHubFetcherService:
    """Fetches commit details from the GitHub API with .patch diff fallback."""

    def __init__(self, config):
        self.config = config

    # ── 1. Fetch Commit Detail (API + .patch) ─────────────────────────

    def fetch_commit_detail(self, sha: str, repo: str) -> FetchedCommitDetail:
        """
        Calls the GitHub API for a single commit and also fetches the .patch diff.

        Uses the API endpoint for structured file data, and the .patch URL
        (reused from OLD_GITHUB_PIPELINE/processor.py) for the raw diff text
        which may give more useful content for the LLM.

        Args:
            sha: Full commit SHA.
            repo: "owner/repo" string.

        Returns:
            FetchedCommitDetail with files, stats, and patch_diff.

        Raises:
            GitHubFetchError: On non-retryable errors (404, 401).
            GitHubRetryableError: On retryable errors (403, 429, 5xx, timeout).
        """
        # ── Fetch structured data from API ────────────────────────────
        api_url = f"{self.config.github_api_base}/repos/{repo}/commits/{sha}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            response = requests.get(api_url, headers=headers, timeout=10)
        except requests.exceptions.Timeout:
            raise GitHubRetryableError(f"GitHub API timeout for {sha[:8]}")
        except requests.exceptions.RequestException as e:
            raise GitHubRetryableError(f"GitHub API request error for {sha[:8]}: {e}")

        # ── Error Handling ────────────────────────────────────────────
        if response.status_code == 404:
            raise GitHubFetchError("GitHub API 404 — commit not found")
        if response.status_code == 401:
            raise GitHubFetchError("GitHub API 401 — invalid token")
        if response.status_code in (403, 429) or response.status_code >= 500:
            raise GitHubRetryableError(
                f"GitHub API {response.status_code} for {sha[:8]}"
            )
        if response.status_code != 200:
            raise GitHubFetchError(
                f"GitHub API unexpected status {response.status_code} for {sha[:8]}"
            )

        detail = self._parse_api_response(response.json())

        # ── Fetch .patch diff (reused from OLD_GITHUB_PIPELINE/processor.py) ──
        patch_diff = self._fetch_patch_diff(sha, repo)
        detail.patch_diff = patch_diff

        # Apply diff size cap
        detail = self._apply_diff_cap(detail)

        return detail

    # ── 2. Fetch .patch Diff ──────────────────────────────────────────

    def _fetch_patch_diff(self, sha: str, repo: str) -> Optional[str]:
        """
        Fetches the raw .patch diff from GitHub.

        Reused pattern from OLD_GITHUB_PIPELINE/processor.py:
        {commit_url}.patch with the right Accept header.
        """
        patch_url = f"https://github.com/{repo}/commit/{sha}.patch"
        headers = {
            "Accept": "application/vnd.github.v3.patch",
            "User-Agent": USER_AGENT,
        }

        try:
            response = requests.get(patch_url, headers=headers, timeout=GITHUB_DIFF_TIMEOUT)
            if response.status_code == 200 and response.text.strip():
                logger.info("Fetched .patch diff for SHA=%s (%d chars)", sha[:8], len(response.text))
                return response.text
            else:
                logger.warning("Could not fetch .patch diff for SHA=%s (status=%d)", sha[:8], response.status_code)
                return None
        except Exception as e:
            logger.warning("Error fetching .patch diff for SHA=%s: %s", sha[:8], e)
            return None

    # ── 3. Parse API Response ─────────────────────────────────────────

    def _parse_api_response(self, data: dict) -> FetchedCommitDetail:
        """Extracts structured fields from the GitHub API commit response."""
        stats = data.get("stats", {})
        files_raw = data.get("files", [])

        files = [
            FetchedFileDetail(
                filename=f["filename"],
                status=f["status"],
                additions=f["additions"],
                deletions=f["deletions"],
                patch=f.get("patch"),
            )
            for f in files_raw
        ]

        return FetchedCommitDetail(
            committed_at=data["commit"]["author"]["date"],
            commit_message=data["commit"]["message"],
            stats_total=stats.get("total", 0),
            stats_additions=stats.get("additions", 0),
            stats_deletions=stats.get("deletions", 0),
            files=files,
            diff_was_truncated=False,
            patch_diff=None,
        )

    # ── 4. Diff Size Cap ──────────────────────────────────────────────

    def _apply_diff_cap(self, detail: FetchedCommitDetail) -> FetchedCommitDetail:
        """
        Truncates file patches proportionally if total exceeds max_diff_chars.

        Each file gets a share of the budget proportional to its patch size.
        """
        files_with_patches = [f for f in detail.files if f.patch]
        if not files_with_patches:
            return detail

        total_chars = sum(len(f.patch) for f in files_with_patches)
        if total_chars <= self.config.max_diff_chars:
            return detail

        per_file_budget = self.config.max_diff_chars // len(files_with_patches)
        for f in files_with_patches:
            if f.patch and len(f.patch) > per_file_budget:
                f.patch = f.patch[:per_file_budget] + "\n... [diff truncated]"

        detail.diff_was_truncated = True
        logger.info(
            "Diff truncated: %d chars → %d chars budget (%d files)",
            total_chars, self.config.max_diff_chars, len(files_with_patches),
        )

        return detail


# ── Custom Exceptions ─────────────────────────────────────────────────

class GitHubFetchError(Exception):
    """Non-retryable GitHub API error (404, 401)."""
    pass


class GitHubRetryableError(Exception):
    """Retryable GitHub API error (403, 429, 5xx, timeout)."""
    pass
