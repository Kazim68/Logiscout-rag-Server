"""Vector Store Service: Embeds commit semantic text and upserts into Qdrant."""

import logging
import uuid
from typing import List

from .models import CommitDocument

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"


class VectorStoreService:
    """Handles embedding generation and Qdrant upsert operations for commits."""

    def __init__(self, config):
        self.config = config
        self._model = None
        self._client = None

    @staticmethod
    def _resolve_model_path(model_name: str) -> str:
        """
        Resolves a concrete local snapshot path.

        If the model is cached, this stays fully offline. If not, it downloads
        once for the current run and returns the downloaded snapshot path.
        """
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            model_path = snapshot_download(repo_id=model_name, local_files_only=True)
            logger.info("Model '%s' found in cache; loading offline", model_name)
            return model_path
        except LocalEntryNotFoundError:
            logger.info("Model '%s' not cached; downloading once for this run", model_name)
            return snapshot_download(repo_id=model_name)

    def get_embedding_model(self):
        """Loads the sentence-transformer model from a local snapshot path."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model_path = self._resolve_model_path(MODEL_NAME)
            self._model = SentenceTransformer(model_path)
            logger.info("Embedding model loaded from local path: %s", model_path)
        return self._model

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Vectorizes a list of semantic text strings."""
        model = self.get_embedding_model()
        embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)
        return [e.tolist() for e in embeddings]

    def get_qdrant_client(self):
        """Creates and caches a Qdrant client connection."""
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self.config.qdrant_url)
            logger.info("Qdrant client connected: %s", self.config.qdrant_url)
        return self._client

    # ── Collection Setup ──────────────────────────────────────────────

    def ensure_collection(self, collection_name: str) -> None:
        """Creates the Qdrant collection if it doesn't exist, then ensures payload indexes."""
        from qdrant_client.models import Distance, VectorParams

        client = self.get_qdrant_client()
        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", collection_name)
        else:
            logger.info("Qdrant collection already exists: %s", collection_name)

        self._ensure_payload_indexes(client, collection_name)

    def _ensure_payload_indexes(self, client, collection_name: str) -> None:
        """Creates payload indexes on fields used for filtering and grouping."""
        from qdrant_client.models import PayloadSchemaType

        # Index list per v2 spec
        indexed_fields = {
            "commit_sha":           PayloadSchemaType.KEYWORD,
            "repo":                 PayloadSchemaType.KEYWORD,
            "service":              PayloadSchemaType.KEYWORD,
            "branch":               PayloadSchemaType.KEYWORD,
            "author":               PayloadSchemaType.KEYWORD,
            "change_type":          PayloadSchemaType.KEYWORD,
            "risk_level":           PayloadSchemaType.KEYWORD,
            "affected_systems":     PayloadSchemaType.KEYWORD,
            "committed_at_unix":    PayloadSchemaType.INTEGER,
            "files_count":          PayloadSchemaType.INTEGER,
            "llm_failed":           PayloadSchemaType.KEYWORD,
        }

        for field_name, field_type in indexed_fields.items():
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_type,
            )

        logger.info(
            "Payload indexes ensured for %s field(s) on '%s'",
            len(indexed_fields), collection_name,
        )

    # ── Deduplication Check ───────────────────────────────────────────

    def _commit_exists_in_qdrant(self, client, collection_name: str, commit_sha: str) -> bool:
        """
        Scrolls Qdrant for existing points with matching commit_sha.

        Second deduplication layer on top of MongoDB.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        results = client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="commit_sha",
                        match=MatchValue(value=commit_sha),
                    )
                ]
            ),
            limit=1,
        )
        points = results[0] if results else []
        return len(points) > 0

    # ── Upsert Commits ────────────────────────────────────────────────

    def upsert_commits(self, commit_documents: List[CommitDocument], collection_name: str) -> int:
        """
        Embeds and upserts CommitDocuments into Qdrant.

        Each point represents one commit:
        - id: generated UUID4 (not the SHA — Qdrant expects UUID format)
        - vector: embedding of the commit's semantic_text
        - payload: vector_metadata + semantic_text

        Skips commits that already exist in Qdrant (deduplication).
        """
        from qdrant_client.models import PointStruct

        if not commit_documents:
            return 0

        client = self.get_qdrant_client()
        self.ensure_collection(collection_name)

        # Filter out commits already in Qdrant
        docs_to_upsert = []
        for doc in commit_documents:
            if self._commit_exists_in_qdrant(client, collection_name, doc.commit_sha):
                logger.info("Commit already in Qdrant, skipping — SHA=%s", doc.commit_sha[:8])
            else:
                docs_to_upsert.append(doc)

        if not docs_to_upsert:
            logger.info("All commits already in Qdrant — nothing to upsert")
            return 0

        texts = [doc.semantic_text for doc in docs_to_upsert]
        vectors = self.embed_batch(texts)

        points = []
        for doc, vector in zip(docs_to_upsert, vectors):
            payload = {
                **doc.vector_metadata,
                "semantic_text": doc.semantic_text,
            }

            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=payload,
            ))

        batch_size = self.config.upsert_batch_size
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            client.upsert(
                collection_name=collection_name,
                points=batch,
            )

        logger.info(
            "Upserted %s commit(s) into Qdrant collection '%s'",
            len(points),
            collection_name,
        )
        return len(points)
