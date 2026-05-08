"""Vector retrieval step for response pipeline context lookup."""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Callable, Dict, List, Optional

from ..config import ResponsePipelineConfig

logger = logging.getLogger(__name__)


def _normalize_vector(vector: Any) -> List[float]:
    """Return a unit-length vector to preserve cosine search behavior."""
    values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]


class VectorRetrievalStep:
    """Retrieves response context from vector storage."""

    def __init__(
        self,
        config: ResponsePipelineConfig,
        qdrant_client_getter: Callable[[], Any],
    ) -> None:
        self.config = config
        self._qdrant_client_getter = qdrant_client_getter
        self._model = None

    def get_embedding_model(self):
        """Lazily load the FastEmbed model used for query embeddings."""
        if self._model is None:
            from fastembed import TextEmbedding

            cache_dir = os.getenv("FASTEMBED_CACHE_PATH") or None
            self._model = TextEmbedding(
                model_name=self.config.embedding_model,
                cache_dir=cache_dir,
            )
            logger.info("Response FastEmbed model loaded: %s", self.config.embedding_model)
        return self._model

    def _embed_query(self, text: str) -> List[float]:
        """Embed the user prompt into the same vector space as commit docs."""
        embedding = list(self.get_embedding_model().query_embed(query=text))[0]
        return _normalize_vector(embedding)

    def _collection_exists(self, collection_name: str) -> bool:
        """Check whether the target collection exists in Qdrant."""
        client = self._qdrant_client_getter()
        collections = client.get_collections().collections
        return any(collection.name == collection_name for collection in collections)

    def _collection_name_for(self, project_id: str, source_type: str) -> str:
        """Build the project-scoped Qdrant collection name for a source type."""
        suffix_by_type = {
            "logs": self.config.logs_collection_suffix,
            "commits": self.config.commits_collection_suffix,
            "postmortem": self.config.postmortem_collection_suffix,
        }
        return f"{project_id}{suffix_by_type[source_type]}"

    @staticmethod
    def _format_hit(hit: Any) -> Dict[str, Any]:
        """Normalize a Qdrant hit into the response contract."""
        payload = dict(hit.payload or {})
        semantic_text = payload.pop("semantic_text", "")

        return {
            "id": str(hit.id),
            "score": float(hit.score),
            "semantic_text": semantic_text,
            "metadata": payload,
        }

    def _search_collection_context(self, collection_name: str, user_prompt: str) -> List[Dict[str, Any]]:
        """Query a Qdrant collection for the most relevant documents."""
        if not user_prompt.strip():
            return []

        if not self._collection_exists(collection_name):
            logger.info("Qdrant collection '%s' does not exist yet; returning empty context", collection_name)
            return []

        client = self._qdrant_client_getter()
        query_vector = self._embed_query(user_prompt)
        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=self.config.top_k,
                score_threshold=self.config.score_threshold,
                with_payload=True,
                with_vectors=False,
            )
            hits = response.points
        else:
            hits = client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=self.config.top_k,
                score_threshold=self.config.score_threshold,
                with_payload=True,
            )
        return [self._format_hit(hit) for hit in hits]

    def retrieve_contexts(
        self,
        *,
        project_id: str,
        user_prompt: str,
        needs_logs: bool,
        needs_commits: bool,
        needs_postmortem: bool,
    ) -> Dict[str, Optional[List[Dict[str, Any]]]]:
        """Return retrieval context grouped by source."""
        contexts: Dict[str, Optional[List[Dict[str, Any]]]] = {
            "log_context": None,
            "commit_context": None,
            "postmortem_context": None,
        }

        try:
            if needs_commits:
                contexts["commit_context"] = self._search_collection_context(
                    collection_name=self._collection_name_for(project_id, "commits"),
                    user_prompt=user_prompt,
                )

            if needs_logs:
                contexts["log_context"] = self._search_collection_context(
                    collection_name=self._collection_name_for(project_id, "logs"),
                    user_prompt=user_prompt,
                )

            if needs_postmortem:
                contexts["postmortem_context"] = self._search_collection_context(
                    collection_name=self._collection_name_for(project_id, "postmortem"),
                    user_prompt=user_prompt,
                )
        except Exception as exc:
            logger.error("Vector retrieval failed for project '%s': %s", project_id, exc, exc_info=True)

        return contexts

    def retrieve_vectors(self, **kwargs):
        """Backward-compatible alias for older internal callers."""
        return self.retrieve_contexts(**kwargs)

    def retrive_vectors(self, **kwargs):
        """Backward-compatible alias for the legacy misspelled method name."""
        return self.retrieve_contexts(**kwargs)
