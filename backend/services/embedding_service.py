"""
services/embedding_service.py - Text embeddings + vector storage (hybrid)

Uses BGE-M3 via FlagEmbedding to produce both dense (1024-d) and sparse vectors.
Stores them as named vectors in Qdrant and retrieves using RRF fusion.

Qdrant = semantic index only (no chunk text in payload).
Postgres = source of truth for chunk text (fetched by chunk_id after retrieval).
"""

import glob
import logging
import os
import time
import uuid
from typing import Optional

from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams, NamedVector,
    PointStruct, SparseVector,
    Filter, FieldCondition, MatchValue,
    Prefetch, FusionQuery, Fusion,
    PayloadSchemaType,
)
from sqlalchemy.orm import Session

from config import get_settings
from models import Chunk
from services.metrics import CHUNKS_EMBEDDED_TOTAL, EMBEDDING_DURATION

logger = logging.getLogger(__name__)
settings = get_settings()

_embedding_model: Optional[BGEM3FlagModel] = None


def _model_cache_dir(model_name: str) -> str:
    hf_home = os.environ.get("HF_HOME", "/root/.cache/huggingface")
    return os.path.join(hf_home, "hub", "models--" + model_name.replace("/", "--"))


def _is_model_cached(model_name: str) -> bool:
    snapshots = os.path.join(_model_cache_dir(model_name), "snapshots")
    return os.path.isdir(snapshots) and bool(os.listdir(snapshots))


def _cleanup_incomplete_blobs(model_name: str) -> None:
    blobs_dir = os.path.join(_model_cache_dir(model_name), "blobs")
    for path in glob.glob(os.path.join(blobs_dir, "*.incomplete")):
        try:
            os.remove(path)
            logger.info("Removed incomplete blob: %s", path)
        except OSError:
            pass


def get_embedding_model() -> BGEM3FlagModel:
    global _embedding_model
    if _embedding_model is None:
        model_name = settings.embedding_model
        cached = _is_model_cached(model_name)
        if not cached:
            _cleanup_incomplete_blobs(model_name)
        logger.info("Loading BGE-M3 model", extra={
            "event": "model_load_start",
            "model": model_name,
            "cached": cached,
        })
        _embedding_model = BGEM3FlagModel(model_name, use_fp16=True, local_files_only=cached)
        logger.info("BGE-M3 model loaded", extra={"event": "model_load_complete", "model": model_name})
    return _embedding_model


class EmbeddingService:
    def __init__(self):
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        self.collection_was_recreated = self._ensure_collection()

    def _ensure_collection(self) -> bool:
        """
        Ensure the Qdrant collection uses named vectors (dense + sparse).
        Recreates the collection if it doesn't exist or uses old single-vector format.
        Returns True if recreated/created (caller resets is_embedded flags).
        """
        try:
            info = self.qdrant.get_collection(settings.qdrant_collection)
            # Check if it's already using named vectors
            params = info.config.params.vectors
            sparse_params = info.config.params.sparse_vectors
            if isinstance(params, dict) and "dense" in params and sparse_params and "sparse" in sparse_params:
                logger.debug(f"Collection '{settings.qdrant_collection}' already uses named hybrid vectors")
                return False
            # Old format – recreate
            logger.warning("Collection is in old single-vector format. Recreating for hybrid named vectors.")
            self.qdrant.delete_collection(settings.qdrant_collection)
        except Exception:
            pass  # Collection doesn't exist

        logger.info(f"Creating hybrid named-vector collection '{settings.qdrant_collection}'")
        self.qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={"dense": VectorParams(size=settings.embedding_dim, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )

        # Add payload indexes for efficient filtered retrieval
        for field_name, schema_type in [
            ("source_id", PayloadSchemaType.KEYWORD),
            ("document_id", PayloadSchemaType.KEYWORD),
            ("chunk_type", PayloadSchemaType.KEYWORD),
            ("language", PayloadSchemaType.KEYWORD),
            ("created_ts", PayloadSchemaType.INTEGER),
        ]:
            try:
                self.qdrant.create_payload_index(
                    collection_name=settings.qdrant_collection,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception as e:
                logger.warning(f"Could not create payload index for {field_name}: {e}")

        return True

    def embed_text(self, text: str) -> dict:
        """Returns {'dense': [...], 'sparse': {indices: [...], values: [...]}}"""
        model = get_embedding_model()
        output = model.encode([text], return_dense=True, return_sparse=True)
        dense = output['dense_vecs'][0].tolist()
        sparse_weights = output['lexical_weights'][0]
        indices = [int(k) for k in sparse_weights.keys()]
        values = [float(v) for v in sparse_weights.values()]
        return {"dense": dense, "sparse": {"indices": indices, "values": values}}

    def embed_chunks(self, db: Session, document_id: str):
        """Embed all un-embedded chunks for a document and upsert into Qdrant."""
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id, Chunk.is_embedded == False)
            .all()
        )
        if not chunks:
            logger.info(f"No unembedded chunks for document {document_id}")
            return

        logger.info(f"Embedding {len(chunks)} chunks for document {document_id}")
        model = get_embedding_model()
        texts = [chunk.text for chunk in chunks]

        output = model.encode(texts, return_dense=True, return_sparse=True)
        dense_vecs = output['dense_vecs']
        sparse_weights_list = output['lexical_weights']

        from models import Document
        doc = db.query(Document).filter(Document.id == document_id).first()
        source_id = doc.source_id if doc else None

        t0 = time.time()
        points = []
        for chunk, dense_vec, sparse_weights in zip(chunks, dense_vecs, sparse_weights_list):
            indices = [int(k) for k in sparse_weights.keys()]
            values = [float(v) for v in sparse_weights.values()]
            point = PointStruct(
                id=str(uuid.UUID(chunk.id)) if "-" in chunk.id else chunk.id,
                vector={
                    "dense": dense_vec.tolist(),
                    "sparse": SparseVector(indices=indices, values=values),
                },
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "source_id": source_id,
                    "citation_url": chunk.citation_url,
                    "chunk_type": chunk.chunk_type.value if chunk.chunk_type else "text",
                    "language": getattr(chunk, 'language', None),
                    "created_ts": int(chunk.created_at.timestamp()) if chunk.created_at else int(time.time()),
                },
            )
            points.append(point)

        try:
            self.qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
        except Exception as e:
            logger.error("Failed to upsert embeddings into Qdrant", extra={
                "event": "embedding_failed",
                "document_id": document_id,
                "chunk_count": len(chunks),
                "reason": str(e),
            })
            raise

        elapsed = time.time() - t0
        for chunk in chunks:
            chunk.is_embedded = True
        db.commit()
        CHUNKS_EMBEDDED_TOTAL.inc(len(chunks))
        EMBEDDING_DURATION.observe(elapsed)
        logger.info("Chunks embedded into Qdrant", extra={
            "event": "embedding_completed",
            "document_id": document_id,
            "chunk_count": len(chunks),
            "elapsed_s": round(elapsed, 3),
        })

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> list[dict]:
        """
        Hybrid search: prefetch 50 from dense, 50 from sparse, fuse with RRF.
        Fetches chunk text from Postgres by chunk_id (single IN query).
        """
        logger.info("Qdrant hybrid search", extra={
            "event": "search_start",
            "query": query[:120],
            "top_k": top_k,
            "source_id": source_id,
        })
        t0 = time.time()
        try:
            model = get_embedding_model()
            output = model.encode([query], return_dense=True, return_sparse=True)
            dense_vec = output['dense_vecs'][0].tolist()
            sparse_weights = output['lexical_weights'][0]
            sparse_indices = [int(k) for k in sparse_weights.keys()]
            sparse_values = [float(v) for v in sparse_weights.values()]

            search_filter = None
            if source_id:
                search_filter = Filter(
                    must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
                )

            results = self.qdrant.query_points(
                collection_name=settings.qdrant_collection,
                prefetch=[
                    Prefetch(
                        query=dense_vec,
                        using="dense",
                        limit=50,
                        filter=search_filter,
                    ),
                    Prefetch(
                        query=SparseVector(indices=sparse_indices, values=sparse_values),
                        using="sparse",
                        limit=50,
                        filter=search_filter,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.error("Qdrant search failed", extra={
                "event": "search_failed",
                "query": query[:120],
                "source_id": source_id,
                "error": str(e),
            }, exc_info=True)
            raise

        hits = results.points

        # Batch-fetch chunk text from Postgres
        chunk_ids = [h.payload.get("chunk_id") for h in hits if h.payload.get("chunk_id")]
        chunk_text_map = {}
        if chunk_ids and db is not None:
            rows = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
            chunk_text_map = {r.id: r.text for r in rows}

        logger.info("Qdrant search complete", extra={
            "event": "search_complete",
            "hits": len(hits),
            "top_k": top_k,
            "elapsed_ms": round((time.time() - t0) * 1000),
        })

        return [
            {
                "chunk_id": h.payload.get("chunk_id"),
                "document_id": h.payload.get("document_id"),
                "text": chunk_text_map.get(h.payload.get("chunk_id"), ""),
                "citation_url": h.payload.get("citation_url"),
                "score": h.score,
            }
            for h in hits
        ]

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        """Remove Qdrant points whose payload chunk_id matches any of the given IDs."""
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        logger.info("Deleting %d chunks from Qdrant", len(chunk_ids), extra={
            "event": "chunks_delete",
            "count": len(chunk_ids),
        })
        self.qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=Filter(
                must=[FieldCondition(key="chunk_id", match=MatchAny(any=chunk_ids))]
            ),
        )
