"""Response-side vector retrieval service for pipeline context lookup."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .config import ResponsePipelineConfig

logger = logging.getLogger(__name__)


class RetrievalService:
    """Retrieves response context from vector storage."""

    def __init__(
        self,
        config: ResponsePipelineConfig,
        qdrant_client_getter: Callable[[], Any],
    ) -> None:
        self.config = config
        self._qdrant_client_getter = qdrant_client_getter
        self._model = None

    @staticmethod
    def _resolve_model_path(model_name: str) -> str:
        """
        Resolve a local snapshot path for the embedding model.

        This mirrors the ingestion pipeline behavior so retrieval uses the
        same embedding space as indexed commit documents.
        """
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            model_path = snapshot_download(repo_id=model_name, local_files_only=True)
            logger.info("Embedding model '%s' found in cache; loading offline", model_name)
            return model_path
        except LocalEntryNotFoundError:
            logger.info("Embedding model '%s' not cached; downloading", model_name)
            return snapshot_download(repo_id=model_name)

    def get_embedding_model(self):
        """Lazily load the sentence-transformer used for query embeddings."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model_path = self._resolve_model_path(self.config.embedding_model)
            self._model = SentenceTransformer(model_path)
            logger.info("Response embedding model loaded from: %s", model_path)
        return self._model

    def _embed_query(self, text: str) -> List[float]:
        """Embed the user prompt into the same vector space as commit docs."""
        embedding = self.get_embedding_model().encode(
            [text],
            normalize_embeddings=True,
            batch_size=1,
        )[0]
        return embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

    def _collection_exists(self, collection_name: str) -> bool:
        """Check whether the target collection exists in Qdrant."""
        client = self._qdrant_client_getter()
        collections = client.get_collections().collections
        return any(collection.name == collection_name for collection in collections)

    @staticmethod
    def _format_commit_hit(hit: Any) -> Dict[str, Any]:
        """Normalize a Qdrant hit into the response contract."""
        payload = dict(hit.payload or {})
        semantic_text = payload.pop("semantic_text", "")

        return {
            "id": str(hit.id),
            "score": float(hit.score),
            "semantic_text": semantic_text,
            "metadata": payload,
        }

    def _search_commit_context(self, collection_name: str, user_prompt: str) -> List[Dict[str, Any]]:
        """Query the commit collection for the most relevant commit documents."""
        if not user_prompt.strip():
            return []

        if not self._collection_exists(collection_name):
            logger.info("Qdrant collection '%s' does not exist yet; returning empty context", collection_name)
            return []

        client = self._qdrant_client_getter()
        query_vector = self._embed_query(user_prompt)
        hits = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=self.config.top_k,
            score_threshold=self.config.score_threshold,
            with_payload=True,
        )
        return [self._format_commit_hit(hit) for hit in hits]

    def retrive_vectors(
        self,
        *,
        collection_name: str,
        user_prompt: str,
        needs_logs: bool,
        needs_commits: bool,
        needs_postmortem: bool,
    ) -> Dict[str, Optional[List[Dict[str, Any]]]]:
        """
        Return retrieval context grouped by source.

        The function name intentionally follows the existing request contract.
        """
        contexts: Dict[str, Optional[List[Dict[str, Any]]]] = {
            "log_context": None,
            "commit_context": None,
            "postmartems_context": None,
        }

        try:
            if needs_commits:
                contexts["commit_context"] = self._search_commit_context(
                    collection_name=collection_name,
                    user_prompt=user_prompt,
                )

            if needs_logs:
                logger.info("Log retrieval requested but not implemented yet; returning empty log_context")
                contexts["log_context"] = []

            if needs_postmortem:
                logger.info(
                    "Postmortem retrieval requested but not implemented yet; returning empty postmartems_context"
                )
                contexts["postmartems_context"] = []
        except Exception as exc:
            logger.error("Vector retrieval failed for collection '%s': %s", collection_name, exc, exc_info=True)

        return contexts

    def retrieve_vectors(self, **kwargs):
        """Correctly spelled alias for internal callers."""
        return self.retrive_vectors(**kwargs)
