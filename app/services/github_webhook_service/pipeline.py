"""
LogiScout Commit Ingestion Pipeline — Direct Processing (v2, no MongoDB).

Usage (from webhook processor):
    from app.services.github_webhook_service.config import CommitPipelineConfig
    from app.services.github_webhook_service.pipeline import CommitIngestionPipeline

    config = CommitPipelineConfig.from_env()
    pipeline = CommitIngestionPipeline(config)
    doc = pipeline.process_webhook_commit(commit_data, repo, branch, project_id)
"""

import logging
from typing import Dict, Any, Optional

from .pipeline_services import (
    GitHubFetcherService,
    DiffAnalyzerService,
    LLMSummarizerService,
    IndexingPrepService,
    VectorStoreService,
    RawCommitPayload,
    CommitDocument,
)
from .pipeline_services.github_fetcher import GitHubFetchError, GitHubRetryableError

logger = logging.getLogger(__name__)


class CommitIngestionPipeline:
    """
    Direct commit processing pipeline.

    Coordinates:
        Webhook → GitHubFetcher → DiffAnalyzer → LLMSummarizer
               → IndexingPrep → VectorStore (Qdrant)

    No MongoDB queue. No background worker. Processes synchronously.
    """

    def __init__(self, config):
        self.config = config
        self.github_fetcher = GitHubFetcherService(config)
        self.diff_analyzer = DiffAnalyzerService(config)
        self.llm_summarizer = LLMSummarizerService(config)
        self.indexing_prep = IndexingPrepService()
        self.vector_store = VectorStoreService(config)

    # ── Main Entry Point ──────────────────────────────────────────────

    def process_webhook_commit(
        self,
        commit_data: Dict[str, Any],
        repo: str,
        branch: str,
        project_id: str,
    ) -> Optional[CommitDocument]:
        """
        Process a single webhook commit through all pipeline stages.

        Args:
            commit_data: Single commit dict from GitHub webhook push event.
                         Has fields: id, message, author.name, author.username,
                         url, timestamp, added, removed, modified.
            repo: "owner/repo" string from payload["repository"]["full_name"].
            branch: Branch name extracted from ref.
            project_id: Project ID for Qdrant collection scoping.

        Returns:
            CommitDocument on success, None on failure.
        """
        sha = commit_data["id"]

        try:
            logger.info("Pipeline start — SHA=%s, repo=%s, project=%s", sha[:7], repo, project_id)

            # Build RawCommitPayload from webhook commit format
            raw_payload = self._build_raw_payload(commit_data, repo, branch, project_id)

            # Stage 2: Fetch full commit detail from GitHub API
            fetched = self.github_fetcher.fetch_commit_detail(sha, repo)

            # Stage 3: Deterministic diff analysis
            diff_analysis = self.diff_analyzer.analyze(fetched.files, repo)

            # Stage 4: LLM summarization
            llm_summary = self.llm_summarizer.summarize(fetched, diff_analysis, raw_payload)

            # Stage 5: Indexing prep
            commit_doc = self.indexing_prep.prepare_commit_document(
                raw_payload, fetched, diff_analysis, llm_summary,
            )

            # Stage 6: Upsert to project-scoped Qdrant collection
            collection_name = f"{project_id}_commits"
            self.vector_store.upsert_commits([commit_doc], collection_name=collection_name)

            logger.info("Pipeline complete — SHA=%s, collection=%s", sha[:7], collection_name)
            return commit_doc

        except (GitHubFetchError, GitHubRetryableError) as e:
            logger.error("GitHub fetch error for SHA=%s: %s", sha[:7], e)
            return None

        except Exception as e:
            logger.error("Pipeline error for SHA=%s: %s", sha[:7], e, exc_info=True)
            return None

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _build_raw_payload(
        commit_data: Dict[str, Any],
        repo: str,
        branch: str,
        project_id: str,
    ) -> RawCommitPayload:
        """
        Build a RawCommitPayload from the webhook push event commit format.

        Webhook commit format differs from API commit format:
        - "id" instead of "sha"
        - "author.username" instead of top-level "author.login"
        - "url" instead of "html_url"
        - No "parents" list
        """
        sha = commit_data["id"]
        author_info = commit_data.get("author", {})

        return RawCommitPayload(
            sha=sha,
            repo=repo,
            project_id=project_id,
            author_login=author_info.get("username", "unknown"),
            author_name=author_info.get("name", "unknown"),
            committed_at=commit_data.get("timestamp", ""),
            commit_message=commit_data.get("message", ""),
            branch=branch,
            html_url=commit_data.get("url", f"https://github.com/{repo}/commit/{sha}"),
            parents=[],
        )
