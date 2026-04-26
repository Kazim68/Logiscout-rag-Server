"""Indexing Prep Service: Builds semantic_text and vector_metadata for commit documents."""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from .models import (
    RawCommitPayload, FetchedCommitDetail, DiffAnalysis,
    LLMCommitSummary, CommitDocument,
)

logger = logging.getLogger(__name__)


class IndexingPrepService:
    """Prepares commit-level documents for vector embedding and Qdrant storage."""

    # ── 1. Semantic Text Builder ──────────────────────────────────────

    def build_semantic_text(
        self,
        raw_payload: RawCommitPayload,
        fetched: FetchedCommitDetail,
        diff_analysis: DiffAnalysis,
        llm_summary: LLMCommitSummary,
    ) -> str:
        """
        Builds a natural-language string optimized for embedding quality.

        Includes: change_type, author, repo, branch, list of changed files,
        affected systems, risk level, and the LLM summary (or raw commit message).

        Cap at 1500 characters. Must never be empty.
        """
        all_filenames = [f.filename for f in fetched.files]
        parts = []

        # Line 1: change type, author, repo, branch
        parts.append(
            f"{diff_analysis.change_type} by {raw_payload.author_login} "
            f"in {raw_payload.repo} on branch {raw_payload.branch}."
        )

        # Line 2: files changed
        files_str = ", ".join(all_filenames)
        parts.append(f"Changed {len(all_filenames)} file(s): {files_str}.")

        # Line 3: affected systems
        systems_str = ", ".join(diff_analysis.affected_systems)
        parts.append(f"Affected systems: {systems_str}.")

        # Line 4: risk
        parts.append(f"Risk: {diff_analysis.risk_level}.")

        # Line 5: summary (LLM or raw commit message fallback)
        summary_text = llm_summary.summary or raw_payload.commit_message
        parts.append(f"Summary: {summary_text}.")

        semantic_text = "\n".join(parts)

        # Cap at 1500 characters
        max_chars = 1500
        if len(semantic_text) > max_chars:
            truncated = semantic_text[:max_chars]
            last_period = truncated.rfind(".")
            if last_period > 0:
                semantic_text = truncated[:last_period + 1] + "..."
            else:
                semantic_text = truncated + "..."

        # Minimum fallback — must never be empty
        if not semantic_text.strip():
            semantic_text = f"{diff_analysis.change_type} commit by {raw_payload.author_login} in {raw_payload.repo}."

        return semantic_text

    # ── 2. Vector Metadata Builder ────────────────────────────────────

    def build_vector_metadata(
        self,
        raw_payload: RawCommitPayload,
        fetched: FetchedCommitDetail,
        diff_analysis: DiffAnalysis,
        llm_summary: LLMCommitSummary,
    ) -> Dict[str, Any]:
        """
        Builds the flat metadata dict for Qdrant's filterable payload.

        All fields here are indexed for fast filtered search.
        Service names in affected_systems must match the log pipeline's names.
        """
        # Parse committed_at to unix epoch
        committed_at_unix = 0
        try:
            dt = datetime.fromisoformat(raw_payload.committed_at.replace("Z", "+00:00"))
            committed_at_unix = int(dt.timestamp())
        except (ValueError, AttributeError):
            logger.warning("Could not parse committed_at for SHA=%s", raw_payload.sha[:8])

        # Primary service: affected_systems[0] or repo name — must never be null
        service = diff_analysis.affected_systems[0] if diff_analysis.affected_systems else raw_payload.repo

        all_filenames = [f.filename for f in fetched.files]

        return {
            # Identity
            "commit_sha":           raw_payload.sha,
            "repo":                 raw_payload.repo,
            "project_id":           raw_payload.project_id,
            "branch":               raw_payload.branch,
            "author":               raw_payload.author_login,
            "html_url":             raw_payload.html_url,

            # Timing
            "committed_at":         raw_payload.committed_at,
            "committed_at_unix":    committed_at_unix,
            "ingested_at":          datetime.now(timezone.utc).isoformat(),

            # Classification (from DiffAnalyzer)
            "change_type":          diff_analysis.change_type,
            "risk_level":           diff_analysis.risk_level,
            "affected_systems":     diff_analysis.affected_systems,
            "service":              service,

            # File details
            "files_changed":        all_filenames,
            "files_added":          diff_analysis.files_added,
            "files_modified":       diff_analysis.files_modified,
            "files_deleted":        diff_analysis.files_deleted,
            "files_count":          len(all_filenames),
            "additions":            fetched.stats_additions,
            "deletions":            fetched.stats_deletions,
            "diff_was_truncated":   fetched.diff_was_truncated,

            # LLM output signals
            "llm_failed":           llm_summary.llm_failed,

            # Flags
            "is_merge_commit":      False,  # always False — merge commits are skipped earlier
        }

    # ── 3. Prepare Commit Document ────────────────────────────────────

    def prepare_commit_document(
        self,
        raw_payload: RawCommitPayload,
        fetched: FetchedCommitDetail,
        diff_analysis: DiffAnalysis,
        llm_summary: LLMCommitSummary,
    ) -> CommitDocument:
        """
        Creates a single CommitDocument from all upstream stage outputs.
        One CommitDocument = one vector in Qdrant.
        """
        semantic_text = self.build_semantic_text(
            raw_payload, fetched, diff_analysis, llm_summary,
        )
        vector_metadata = self.build_vector_metadata(
            raw_payload, fetched, diff_analysis, llm_summary,
        )

        return CommitDocument(
            commit_sha=raw_payload.sha,
            repo=raw_payload.repo,
            project_id=raw_payload.project_id,
            semantic_text=semantic_text,
            vector_metadata=vector_metadata,
        )
