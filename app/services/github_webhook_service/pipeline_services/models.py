"""Pydantic models for the LogiScout commit ingestion pipeline."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


# ============================================ #
#  Webhook / Queue Schemas                     #
# ============================================ #

class RawCommitPayload(BaseModel):
    """Stripped webhook payload for pipeline processing."""
    sha: str
    repo: str
    project_id: str
    author_login: str
    author_name: str
    committed_at: str
    commit_message: str
    branch: str
    html_url: str
    parents: List[str]


# ============================================ #
#  GitHub Fetcher Schemas                      #
# ============================================ #

class FetchedFileDetail(BaseModel):
    """Single file entry from GitHub API commit detail."""
    filename: str
    status: str                     # added / modified / deleted / renamed
    additions: int
    deletions: int
    patch: Optional[str] = None     # None for binary or oversized files


class FetchedCommitDetail(BaseModel):
    """Output of GitHubFetcherService."""
    committed_at: str
    commit_message: str
    stats_total: int
    stats_additions: int
    stats_deletions: int
    files: List[FetchedFileDetail]
    diff_was_truncated: bool = False
    patch_diff: Optional[str] = None  # raw .patch diff from GitHub


# ============================================ #
#  Diff Analyzer Schema                        #
# ============================================ #

class DiffAnalysis(BaseModel):
    """Output of DiffAnalyzerService."""
    change_type: str
    risk_level: str
    affected_systems: List[str]
    files_added: List[str]
    files_modified: List[str]
    files_deleted: List[str]
    files_with_patch: List[str]
    files_without_patch: List[str]


# ============================================ #
#  LLM Summarizer Schema                      #
# ============================================ #

class LLMCommitSummary(BaseModel):
    """Output from configurable LLM provider — plain text summary only."""
    summary: Optional[str] = None
    llm_failed: bool = False


# ============================================ #
#  Output Schema (vector-ready document)       #
# ============================================ #

class CommitDocument(BaseModel):
    """Final vector-ready document. One per commit SHA. Mirrors TraceDocument."""
    commit_sha: str
    repo: str
    project_id: str
    semantic_text: str
    vector_metadata: Dict[str, Any]
