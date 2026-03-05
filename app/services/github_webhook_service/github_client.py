"""GitHub API client for fetching repository commits."""

import requests
from typing import Dict, List, Optional
from datetime import datetime

from app.core.settings import settings
import logging
from app.services.github_webhook_service.groq_client import summarize_diff

logger = logging.getLogger(__name__)

# Configuration
GITHUB_API_URL: str = "https://api.github.com"
REQUEST_TIMEOUT: int = 15
MAX_DIFF_SIZE: int = 8000


def get_headers() -> Dict[str, str]:
    """Get GitHub API headers with optional authentication."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LogiScout-Server"
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
    return headers


def fetch_commit_diff(repo: str, sha: str) -> Optional[str]:
    """
    Fetch the diff for a specific commit.
    
    Args:
        repo: Repository in "owner/repo" format
        sha: Full commit SHA
    
    Returns:
        Diff text or None if failed
    """
    url = f"{GITHUB_API_URL}/repos/{repo}/commits/{sha}"
    
    try:
        response = requests.get(
            url,
            headers={**get_headers(), "Accept": "application/vnd.github.v3.patch"},
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.warning(f"Could not fetch diff for {sha[:7]}: {response.status_code}")
            return None
        
        diff_text = response.text
        # Truncate large diffs
        if len(diff_text) > MAX_DIFF_SIZE:
            diff_text = diff_text[:MAX_DIFF_SIZE] + "\n... (diff truncated)"
        
        return diff_text
        
    except Exception as e:
        logger.warning(f"Error fetching diff for {sha[:7]}: {str(e)}")
        return None


def fetch_recent_commits(count: int = 5) -> List[Dict]:
    """
    Fetch the most recent commits from the configured GitHub repository.
    
    Args:
        count: Number of commits to fetch (default: 5)
    
    Returns:
        List of commit dictionaries with extracted data
    """
    if not settings.GITHUB_REPO:
        logger.warning("GITHUB_REPO not configured in settings")
        return []
    
    url = f"{GITHUB_API_URL}/repos/{settings.GITHUB_REPO}/commits"
    params = {"per_page": count}
    
    try:
        logger.info(f"Fetching {count} recent commits from {settings.GITHUB_REPO}")
        
        response = requests.get(
            url,
            headers=get_headers(),
            params=params,
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code == 404:
            logger.error(f"Repository not found: {settings.GITHUB_REPO}")
            return []
        
        if response.status_code == 401:
            logger.error("GitHub API authentication failed. Check GITHUB_TOKEN.")
            return []
        
        if response.status_code != 200:
            logger.error(f"GitHub API error {response.status_code}: {response.text}")
            return []
        
        commits_data = response.json()
        commits = []
        
        for commit_data in commits_data:
            commit = commit_data.get("commit", {})
            author = commit.get("author", {})
            sha = commit_data.get("sha", "")
            
            # Fetch diff and generate LLM summary
            diff_text = fetch_commit_diff(settings.GITHUB_REPO, sha)
            if diff_text:
                logger.info(f"Generating LLM summary for commit {sha[:7]}")
                summary = summarize_diff(diff_text)
            else:
                summary = commit.get("message", "").split("\n")[0]
            
            entry = {
                "source": "github_api",
                "repo": settings.GITHUB_REPO,
                "commit": sha[:7],
                "full_sha": sha,
                "message": commit.get("message", "").split("\n")[0],
                "author": author.get("name", "Unknown"),
                "pusher": "API Fetch",
                "branch": "main",  # Default branch
                "timestamp": author.get("date", datetime.utcnow().isoformat()),
                "summary": summary
            }
            commits.append(entry)
        
        logger.info(f"Successfully fetched {len(commits)} commits from {settings.GITHUB_REPO}")
        return commits
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching commits from {settings.GITHUB_REPO}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching commits: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching commits: {str(e)}")
        return []
