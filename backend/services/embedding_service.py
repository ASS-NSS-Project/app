"""
services/embedding_service.py - Text embeddings + vector storage

"Embedding" means converting text into a list of numbers (a vector)
that represents its semantic content.

Similar texts produce similar vectors – this enables semantic search:
"What is the population of France?" finds relevant chunks even without exact word matches.

We use the BAAI/bge-m3 model (sentence-transformers, runs locally, no API key required):
- Multilingual (100+ languages)
- Output: 1024-dimensional vectors
- Higher quality than MiniLM, especially for non-English text

Vectors are stored in Qdrant (vector database).
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
        # collection_was_recreated = True signals main.py to reset chunk embeddings
        self.collection_was_recreated = self._ensure_collection()

    def _ensure_collection(self) -> bool:
        """
        Ensures the Qdrant collection exists with the correct dimension.

        If the collection exists but has a different dimension (model change),
        it is deleted and recreated. Returns True if the collection was recreated
        or newly created – the caller can then reset is_embedded flags.
        """
        try:
            info = self.qdrant.get_collection(settings.qdrant_collection)
            existing_dim = info.config.params.vectors.size
            if existing_dim == settings.embedding_dim:
                logger.debug(f"Collection '{settings.qdrant_collection}' exists ({existing_dim}D)")
                return False
            # Dimension mismatch – model was changed, recreate the collection
            logger.warning(
                f"Collection dimension ({existing_dim}D) does not match config "
                f"({settings.embedding_dim}D). Recreating collection..."
            )
            self.qdrant.delete_collection(settings.qdrant_collection)
        except Exception:
            pass  # Collection doesn't exist – we'll create it

        logger.info(
            f"Creating collection '{settings.qdrant_collection}' "
            f"({settings.embedding_dim}D, model: {settings.embedding_model})"
        )
        self.qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.embedding_dim,
                distance=Distance.COSINE,
            ),
        )
        return True

    def embed_text(self, text: str) -> list[float]:
        """
        Converts text into a vector (a list of 1024 floating-point numbers).

        Example:
            "The Eiffel Tower is in Paris"
            -> [0.12, -0.34, 0.56, ...] (1024 numbers)
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

        # Fetch source_id from the document – needed for filtering in Qdrant
        from models import Document
        doc = db.query(Document).filter(Document.id == document_id).first()
        source_id = doc.source_id if doc else None

        # Build Qdrant points
        points = []
        for chunk, vector in zip(chunks, vectors):
            # Each point contains:
            # - id: unique chunk UUID
            # - vector: embedding (list of floats)
            # - payload: metadata for filtering (source, URL, document, type)
            point = PointStruct(
                id=str(uuid.UUID(chunk.id)) if "-" in chunk.id else chunk.id,
                vector=vector.tolist(),
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "source_id": source_id,        # required for filtering by source
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
