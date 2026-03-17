"""
services/embedding_service.py - Text Embeddings + Vector Storage

"Embedding" means converting text into a list of numbers (a vector)
that represents the meaning of the text.

Similar texts get similar vectors. This lets us do semantic search:
"What is the population of France?" finds chunks about French demographics
even if they don't contain those exact words.

We use sentence-transformers (runs locally, no API cost).
The model "all-MiniLM-L6-v2" outputs 384-dimensional vectors.

Vectors are stored in Qdrant (our vector database).
"""

import logging
import uuid
from typing import Optional

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, SearchRequest
)
from sqlalchemy.orm import Session

from config import get_settings
from models import Chunk

logger = logging.getLogger(__name__)
settings = get_settings()

# Module-level singleton for the embedding model.
# Loading a model takes ~2 seconds, so we load it once and reuse.
_embedding_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    """Load the embedding model (once, then cache)."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _embedding_model = SentenceTransformer(settings.embedding_model)
        logger.info("Embedding model loaded successfully")
    return _embedding_model


class EmbeddingService:
    """
    Handles embedding chunks and storing/searching in Qdrant.
    """

    def __init__(self):
        self.qdrant = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        self._ensure_collection()

    def _ensure_collection(self):
        """
        Create the Qdrant collection if it doesn't exist.
        A collection is like a table in a regular database,
        but instead of rows, it stores vectors.
        """
        try:
            self.qdrant.get_collection(settings.qdrant_collection)
            logger.debug(f"Collection '{settings.qdrant_collection}' already exists")
        except Exception:
            logger.info(f"Creating Qdrant collection '{settings.qdrant_collection}'")
            self.qdrant.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=settings.embedding_dim,   # 384 for MiniLM
                    distance=Distance.COSINE,       # Cosine similarity (standard for text)
                ),
            )

    def embed_text(self, text: str) -> list[float]:
        """
        Convert a string into a vector (list of 384 floats).
        
        Example:
            "The Eiffel Tower is in Paris" 
            -> [0.12, -0.34, 0.56, ...] (384 numbers)
        """
        model = get_embedding_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_chunks(self, db: Session, document_id: str):
        """
        Embed all un-embedded chunks for a document and store in Qdrant.
        
        Called after a document is ingested.
        """
        chunks = (
            db.query(Chunk)
            .filter(
                Chunk.document_id == document_id,
                Chunk.is_embedded == False,
            )
            .all()
        )

        if not chunks:
            logger.info(f"No unembedded chunks for document {document_id}")
            return

        logger.info(f"Embedding {len(chunks)} chunks for document {document_id}")
        model = get_embedding_model()

        # Batch encode all chunk texts at once (faster than one by one)
        texts = [chunk.text for chunk in chunks]
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        # Prepare Qdrant points
        points = []
        for chunk, vector in zip(chunks, vectors):
            # Each point has:
            # - id: unique ID (we use the chunk DB id converted to UUID)
            # - vector: the embedding
            # - payload: metadata for filtering (source, URL, document, etc.)
            point = PointStruct(
                id=str(uuid.UUID(chunk.id)) if "-" in chunk.id else chunk.id,
                vector=vector.tolist(),
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "citation_url": chunk.citation_url,
                    "chunk_type": chunk.chunk_type.value if chunk.chunk_type else "text",
                },
            )
            points.append(point)

        # Upsert: insert or update
        self.qdrant.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
        )

        # Mark chunks as embedded in the DB
        for chunk in chunks:
            chunk.is_embedded = True
        db.commit()

        logger.info(f"Embedded {len(chunks)} chunks into Qdrant")

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Search for the most relevant chunks for a query.
        
        How it works:
        1. Convert query to a vector
        2. Find the k vectors in Qdrant closest to the query vector
        3. Return their text + metadata
        
        Args:
            query: The user's question
            top_k: How many chunks to return
            source_id: Optional filter (only search within one source)
        
        Returns:
            List of dicts with text, score, citation_url, etc.
        """
        query_vector = self.embed_text(query)

        # Optional filter to restrict search to a specific source
        search_filter = None
        if source_id:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchValue(value=source_id),
                    )
                ]
            )

        results = self.qdrant.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True,
        )

        return [
            {
                "chunk_id": r.payload.get("chunk_id"),
                "document_id": r.payload.get("document_id"),
                "text": r.payload.get("text"),
                "citation_url": r.payload.get("citation_url"),
                "score": r.score,  # 0.0 to 1.0, higher = more relevant
            }
            for r in results
        ]
