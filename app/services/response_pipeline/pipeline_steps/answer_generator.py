"""Answer generation step for the response pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .ID_fallback_chain import LLMClient, LLMUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class AnswerResult:
    text: str
    provider: str  # "llm" | "fallback"
    error: Optional[str] = None
    raw: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "error": self.error,
        }


class AnswerGenerator:
    """Generates the final user-facing answer from retrieved context."""

    def __init__(self, config, llm_client: Optional[LLMClient] = None):
        self.config = config
        self.llm = llm_client or LLMClient(config)

    async def generate(
        self,
        *,
        vague_context: Any,
        chat_context: Any,
        user_prompt: str,
        intent: str,
        contexts: Dict[str, Optional[List[Dict[str, Any]]]],
    ) -> AnswerResult:
        system_prompt = self.config.answer_system_prompt
        user_msg = self._build_user_prompt(
            vague_context=vague_context,
            chat_context=chat_context,
            user_prompt=user_prompt,
            intent=intent,
            contexts=contexts,
        )

        try:
            raw = await self.llm.complete_with_fallback(system_prompt, user_msg)
        except LLMUnavailableError as exc:
            logger.error("Answer generation failed — LLM unavailable: %s", exc)
            return AnswerResult(
                text=self._fallback_answer(user_prompt=user_prompt, contexts=contexts),
                provider="fallback",
                error=str(exc),
            )

        text = (raw or "").strip()
        if not text:
            return AnswerResult(
                text=self._fallback_answer(user_prompt=user_prompt, contexts=contexts),
                provider="fallback",
                error="LLM returned an empty answer.",
                raw=raw,
            )

        return AnswerResult(
            text=text,
            provider="llm",
            raw=raw,
        )

    def _build_user_prompt(
        self,
        *,
        vague_context: Any,
        chat_context: Any,
        user_prompt: str,
        intent: str,
        contexts: Dict[str, Optional[List[Dict[str, Any]]]],
    ) -> str:
        retrieved_context = self._format_contexts(contexts)
        retrieval_summary = self._summarize_contexts(contexts)

        return self.config.answer_user_prompt_template.format(
            intent=intent,
            vague_context=_stringify(vague_context),
            chat_context=_stringify(chat_context),
            user_prompt=user_prompt,
            retrieval_summary=retrieval_summary,
            retrieved_context=retrieved_context,
        )

    def _format_contexts(self, contexts: Dict[str, Optional[List[Dict[str, Any]]]]) -> str:
        sections: List[str] = []
        bucket_names = {
            "log_context": "Logs",
            "commit_context": "Commits",
            "postmortem_context": "Postmortems",
        }

        for bucket_key, label in bucket_names.items():
            items = _get_context_bucket(contexts, bucket_key)
            if not items:
                sections.append(f"{label}:\n- None")
                continue

            lines = [f"{label}:"]
            for idx, item in enumerate(items[: self.config.answer_items_per_bucket], start=1):
                metadata = item.get("metadata") or {}
                metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
                semantic_text = str(item.get("semantic_text") or "").strip()
                if len(semantic_text) > 900:
                    semantic_text = semantic_text[:900] + "..."

                lines.append(
                    "\n".join(
                        [
                            f"- Item {idx}",
                            f"  score: {item.get('score', 0.0):.4f}",
                            f"  metadata: {metadata_json}",
                            f"  text: {semantic_text or '(empty)'}",
                        ]
                    )
                )
            sections.append("\n".join(lines))

        combined = "\n\n".join(sections)
        if len(combined) > self.config.answer_context_limit:
            return combined[: self.config.answer_context_limit] + "\n...(truncated)"
        return combined

    @staticmethod
    def _summarize_contexts(contexts: Dict[str, Optional[List[Dict[str, Any]]]]) -> str:
        logs_count = len(_get_context_bucket(contexts, "log_context"))
        commits_count = len(_get_context_bucket(contexts, "commit_context"))
        postmortems_count = len(_get_context_bucket(contexts, "postmortem_context"))
        return (
            f"Retrieved {logs_count} log item(s), "
            f"{commits_count} commit item(s), and "
            f"{postmortems_count} postmortem item(s)."
        )

    @staticmethod
    def _fallback_answer(
        *,
        user_prompt: str,
        contexts: Dict[str, Optional[List[Dict[str, Any]]]],
    ) -> str:
        evidence: List[str] = []

        log_context = _get_context_bucket(contexts, "log_context")
        if log_context:
            first_log = log_context[0]
            log_meta = first_log.get("metadata") or {}
            evidence.append(
                f"Logs are available for {log_meta.get('request_path_pattern') or log_meta.get('request_path') or 'the request path'} "
                f"with status {log_meta.get('request_status_code', 'unknown')}."
            )

        commit_context = _get_context_bucket(contexts, "commit_context")
        if commit_context:
            first_commit = commit_context[0]
            commit_meta = first_commit.get("metadata") or {}
            evidence.append(
                f"Relevant commit context is available from {commit_meta.get('commit_sha') or 'a retrieved commit'}."
            )

        postmortem_context = _get_context_bucket(contexts, "postmortem_context")
        if postmortem_context:
            evidence.append("Relevant postmortem context is available.")

        if not evidence:
            evidence.append("No supporting vector context was retrieved for this question.")

        return (
            f"I could not generate a model answer, but here is the available evidence for your question "
            f"'{user_prompt}': " + " ".join(evidence)
        )


def _stringify(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value if value.strip() else "(none)"
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _get_context_bucket(
    contexts: Dict[str, Optional[List[Dict[str, Any]]]],
    bucket_key: str,
) -> List[Dict[str, Any]]:
    legacy_bucket_keys = {
        "postmortem_context": "postmartems_context",
    }
    legacy_bucket_key = legacy_bucket_keys.get(bucket_key, "")
    return (contexts.get(bucket_key) or contexts.get(legacy_bucket_key) or [])
