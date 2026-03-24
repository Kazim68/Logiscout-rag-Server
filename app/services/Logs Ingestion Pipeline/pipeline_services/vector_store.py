"""Vector Store Service: Embeds semantic text and upserts enriched documents into Qdrant."""

import logging
import uuid
from typing import List

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Handles embedding generation and Qdrant upsert operations."""

    def __init__(self, config):
        self.config = config
        self._model = None
        self._client = None

    # ── 1. Embedding Model ────────────────────────────────────────────

    def get_embedding_model(self):
        """Loads and caches the sentence-transformer embedding model."""
        if self._model is None:
            import os
            if self.config.hf_hub_offline:
                os.environ["HF_HUB_OFFLINE"] = "1"
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            logger.info("Embedding model loaded: BAAI/bge-small-en-v1.5")
        return self._model

    # ── 2. Single Text Embedding ──────────────────────────────────────

    def embed_text(self, text: str) -> List[float]:
        """Vectorizes a single semantic_text string."""
        model = self.get_embedding_model()
        return model.encode(text, normalize_embeddings=True).tolist()

    # ── 3. Batch Embedding ────────────────────────────────────────────

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Vectorizes a list of semantic_text strings."""
        model = self.get_embedding_model()
        embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)
        return [e.tolist() for e in embeddings]

    # ── 4. Collection Management ──────────────────────────────────────

    def get_qdrant_client(self):
        """Creates and caches a Qdrant client connection."""
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(url=self.config.qdrant_url)
            logger.info(f"Qdrant client connected: {self.config.qdrant_url}")
        return self._client

    def ensure_collection(self) -> None:
        """Creates the Qdrant collection if it doesn't already exist."""
        from qdrant_client.models import Distance, VectorParams

        client = self.get_qdrant_client()
        collection_name = self.config.collection_logs

        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection: {collection_name}")
        else:
            logger.info(f"Qdrant collection already exists: {collection_name}")

    # ── 5. Upsert Documents ───────────────────────────────────────────

    def upsert_documents(self, documents: List) -> int:
        """
        Embeds and upserts EnrichedDocuments into Qdrant.

        Each point uses:
        - id: generated UUID
        - vector: embedding of semantic_text
        - payload: vector_metadata + semantic_text + ls_id + ls_cid
        """
        from qdrant_client.models import PointStruct

        if not documents:
            return 0

        client = self.get_qdrant_client()
        self.ensure_collection()

        # Batch embed all semantic texts
        texts = [doc.semantic_text for doc in documents]
        vectors = self.embed_batch(texts)

        # Build Qdrant points
        points = []
        for doc, vector in zip(documents, vectors):
            payload = {
                **doc.vector_metadata,
                "semantic_text": doc.semantic_text,
                "ls_id": doc.ls_id,
                "ls_cid": doc.ls_cid,
                "ls_ts": doc.ls_ts,
                "message": doc.payload.message,
            }

            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=payload,
            ))

        # Upsert in configurable batches
        batch_size = self.config.upsert_batch_size
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            client.upsert(
                collection_name=self.config.collection_logs,
                points=batch,
            )

        logger.info(f"Upserted {len(points)} points into Qdrant collection '{self.config.collection_logs}'")
        return len(points)
