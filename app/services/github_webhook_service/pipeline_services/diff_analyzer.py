"""Diff Analyzer Service: Pure deterministic analysis of file paths and changes."""

import fnmatch
import logging
from typing import List

from .models import FetchedFileDetail, DiffAnalysis

logger = logging.getLogger(__name__)


class DiffAnalyzerService:
    """Classifies change type, risk level, and affected systems from file paths."""

    def __init__(self, config):
        self.config = config
        # Import priority lists from config module
        from ..config import CHANGE_TYPE_PRIORITY, RISK_PRIORITY
        self._change_type_priority = CHANGE_TYPE_PRIORITY
        self._risk_priority = RISK_PRIORITY

    # ── 1. Change Type Classification ─────────────────────────────────

    def _classify_change_type(self, filenames: List[str]) -> str:
        """
        Evaluates all file paths against change_type_rules.

        Uses fnmatch for glob matching. Returns the highest-priority
        change type across all files. Default: "unknown".
        """
        best_type = "unknown"
        best_priority = -1

        for filename in filenames:
            for pattern, change_type in self.config.change_type_rules:
                if fnmatch.fnmatch(filename, pattern):
                    priority = (
                        self._change_type_priority.index(change_type)
                        if change_type in self._change_type_priority
                        else -1
                    )
                    if priority > best_priority:
                        best_priority = priority
                        best_type = change_type
                    break  # First match wins per file

        return best_type

    # ── 2. Risk Level Classification ──────────────────────────────────

    def _classify_risk_level(self, filenames: List[str]) -> str:
        """
        Evaluates all file paths against risk_rules.

        Returns the highest risk triggered by any single file.
        Default: "low".
        """
        best_risk = "low"
        best_priority = 0

        for filename in filenames:
            for pattern, risk_level in self.config.risk_rules:
                if fnmatch.fnmatch(filename, pattern):
                    priority = (
                        self._risk_priority.index(risk_level)
                        if risk_level in self._risk_priority
                        else 0
                    )
                    if priority > best_priority:
                        best_priority = priority
                        best_risk = risk_level
                    break  # First match wins per file

        return best_risk

    # ── 3. Affected Systems ───────────────────────────────────────────

    def _identify_affected_systems(self, filenames: List[str], repo: str) -> List[str]:
        """
        Maps file paths to service names using service_path_mapping.

        For each file, checks if any mapping key is a prefix.
        Falls back to repo name if no mapping matches.
        """
        systems = []
        seen = set()

        for filename in filenames:
            for path_prefix, service_name in self.config.service_path_mapping.items():
                if filename.startswith(path_prefix):
                    if service_name not in seen:
                        seen.add(service_name)
                        systems.append(service_name)
                    break

        # If no systems found from mappings, use repo name as fallback
        if not systems:
            systems.append(repo)

        return systems

    # ── 4. Analyze ────────────────────────────────────────────────────

    def analyze(self, files: List[FetchedFileDetail], repo: str = "unknown/unknown") -> DiffAnalysis:
        """
        Runs all deterministic analysis on the list of changed files.

        Args:
            files: List of FetchedFileDetail from GitHubFetcherService.
            repo: "owner/repo" string for fallback service name.

        Returns:
            DiffAnalysis with change_type, risk_level, affected_systems, and file lists.
        """
        filenames = [f.filename for f in files]

        # Classify files by status
        files_added = [f.filename for f in files if f.status == "added"]
        files_modified = [f.filename for f in files if f.status in ("modified", "renamed")]
        files_deleted = [f.filename for f in files if f.status == "deleted"]
        files_with_patch = [f.filename for f in files if f.patch is not None]
        files_without_patch = [f.filename for f in files if f.patch is None]

        # Run classifications
        change_type = self._classify_change_type(filenames)
        risk_level = self._classify_risk_level(filenames)
        affected_systems = self._identify_affected_systems(filenames, repo)

        analysis = DiffAnalysis(
            change_type=change_type,
            risk_level=risk_level,
            affected_systems=affected_systems,
            files_added=files_added,
            files_modified=files_modified,
            files_deleted=files_deleted,
            files_with_patch=files_with_patch,
            files_without_patch=files_without_patch,
        )

        logger.info(
            "Diff analysis — type=%s, risk=%s, systems=%s, files=%d",
            change_type, risk_level, affected_systems, len(filenames),
        )

        return analysis
