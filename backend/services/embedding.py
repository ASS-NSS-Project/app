"""
services/embedding.py - Text embeddings and hybrid vector search

Uses BGE-M3 (BAAI/bge-m3) via FlagEmbedding to produce two types of vectors
for every chunk of text:

  Dense vector (1024 floats):
    A single vector that captures the semantic meaning of the text.
    Queries with the same meaning but different words still match nearby.
    E.g. "tuition cost" matches "university fees" even with zero word overlap.

  Sparse vector (variable-length {index: weight} dict):
    Like BM25: measures exact keyword overlap, token by token.
    Good at matching rare domain-specific terms, proper nouns, codes.

Both vectors are stored in Qdrant as named vectors ("dense" and "sparse") on the
same point. At search time we query both, then use Reciprocal Rank Fusion (RRF)
to merge the two ranked lists into one — the best of both semantic and keyword
search.

Architecture:
  - Qdrant = vector index only. It stores chunk IDs in the payload but NOT the text.
  - Postgres = source of truth for chunk text.
  - After Qdrant returns hit IDs, we fetch the actual text from Postgres in a
    single IN query.

This split keeps Qdrant lean and allows Postgres to be the authoritative store
for chunk content. It also means stale Qdrant vectors (where the Postgres row
was deleted) are harmless — they just return no text and are self-healed.
"""

import glob
import logging
import os
import time
import uuid
from datetime import datetime
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
from sqlalchemy import func

from config import get_settings
from models import Chunk
from services.metrics import CHUNKS_EMBEDDED_TOTAL, EMBEDDING_DURATION

logger = logging.getLogger(__name__)
settings = get_settings()

# Module-level singleton for the BGE-M3 model (~2.3 GB loaded in memory).
# Shared across all EmbeddingService instances so the model is loaded only once.
_embedding_model: Optional[BGEM3FlagModel] = None


def _model_cache_dir(model_name: str) -> str:
    """
    Return the HuggingFace cache directory for a model.

    HuggingFace Hub stores models under HF_HOME/hub/models--<org>--<name>/.
    We replace "/" with "--" to match the directory naming convention.
    """
    hf_home = os.environ.get("HF_HOME", "/root/.cache/huggingface")
    return os.path.join(hf_home, "hub", "models--" + model_name.replace("/", "--"))


def _is_model_cached(model_name: str) -> bool:
    """
    Check whether the model has already been fully downloaded.

    HuggingFace marks a downloaded model by creating a "snapshots/" subdirectory
    containing at least one version folder. If this doesn't exist, the model
    needs to be downloaded from the Hub.
    """
    snapshots = os.path.join(_model_cache_dir(model_name), "snapshots")
    return os.path.isdir(snapshots) and bool(os.listdir(snapshots))


def _cleanup_incomplete_blobs(model_name: str) -> None:
    """
    Remove partially-downloaded model blob files left by a previous interrupted download.

    HuggingFace writes "*.incomplete" temporary files during download.
    If the download was interrupted (container killed, OOM, timeout), these files
    remain on disk. BGEM3FlagModel mistakenly treats any file in the blobs/
    directory as a complete, valid blob and crashes with a confusing error instead
    of re-downloading. Deleting them before loading forces a fresh download.
    """
    blobs_dir = os.path.join(_model_cache_dir(model_name), "blobs")
    for path in glob.glob(os.path.join(blobs_dir, "*.incomplete")):
        try:
            os.remove(path)
            logger.info("Removed incomplete blob: %s", path)
        except OSError:
            pass  # already deleted by another process — ignore


def get_embedding_model() -> BGEM3FlagModel:
    """
    Load (or return cached) the BGE-M3 FlagEmbedding model.

    On the very first call this takes ~30 s if the model needs to be downloaded
    from HuggingFace Hub, or ~10 s if the weights are already cached on the hf_cache
    Docker volume. Subsequent calls return the already-loaded model instantly.

    fp16=True halves memory usage (~2.3 GB vs ~4.6 GB) with negligible accuracy loss.
    local_files_only=True when cached: skips the Hub network check (a ~30 s timeout
    in air-gapped Kubernetes pods) when the model is already on disk.
    """
    global _embedding_model
    if _embedding_model is None:
        model_name = settings.embedding_model
        cached = _is_model_cached(model_name)
        if not cached:
            # Clean up any incomplete blobs from a previous failed download
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
    """
    Manages the lifecycle of vector embeddings: creating the Qdrant collection,
    embedding new chunks, and searching for relevant chunks at query time.

    One instance is created per worker process or per request (in the API).
    The underlying BGE-M3 model and Qdrant client are singletons, so multiple
    EmbeddingService instances don't duplicate the model in memory.
    """

    def __init__(self):
        # QdrantClient wraps the REST API of Qdrant (runs at QDRANT_URL in compose/K8s)
        self.qdrant = QdrantClient(url=settings.qdrant_url)
        # Ensure the collection exists with the correct schema.
        # Returns True if the collection was just created or recreated.
        self.collection_was_recreated = self._ensure_collection()

    def _ensure_collection(self) -> bool:
        """
        Ensure the Qdrant collection exists and uses named hybrid vectors.

        Named vectors ("dense" and "sparse") allow a single Qdrant point to carry
        both vector types. Older single-vector collections cannot be migrated in-place
        — they must be deleted and recreated, which means all chunks need re-embedding.

        The collection is also configured with payload indexes for fast filtered search
        (e.g. "only search chunks from source X"). Without indexes, Qdrant must scan
        the entire collection for every filtered query.

        Returns:
            True if the collection was created or recreated (caller should reset
            is_embedded flags in Postgres so chunks get re-embedded).
            False if the collection already existed with the correct schema.
        """
        try:
            info = self.qdrant.get_collection(settings.qdrant_collection)
            params = info.config.params.vectors
            sparse_params = info.config.params.sparse_vectors
            # Check that the collection already uses both named vector types
            if isinstance(params, dict) and "dense" in params and sparse_params and "sparse" in sparse_params:
                logger.debug(f"Collection '{settings.qdrant_collection}' already uses named hybrid vectors")
                return False
            # Old single-vector format — must recreate to support hybrid search
            logger.warning("Collection is in old single-vector format. Recreating for hybrid named vectors.")
            self.qdrant.delete_collection(settings.qdrant_collection)
        except Exception:
            pass  # collection simply doesn't exist yet — proceed to create it

        logger.info(f"Creating hybrid named-vector collection '{settings.qdrant_collection}'")
        self.qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            # Dense vectors: 1024-dimensional cosine similarity (BGE-M3 dense output)
            vectors_config={"dense": VectorParams(size=settings.embedding_dim, distance=Distance.COSINE)},
            # Sparse vectors: no fixed size — indices are token IDs from the vocabulary
            sparse_vectors_config={"sparse": SparseVectorParams()},
            # Replication factor: how many Qdrant nodes hold a copy of each shard.
            # 1 = no replication (default, single node). 3 = HA with 3 Qdrant replicas.
            replication_factor=settings.qdrant_replication_factor,
        )

        # Create payload indexes for the fields we filter by most often.
        # Without an index, Qdrant does a full scan on every filtered query.
        for field_name, schema_type in [
            ("source_id", PayloadSchemaType.KEYWORD),    # filter by source (very common)
            ("document_id", PayloadSchemaType.KEYWORD),  # filter by document
            ("chunk_type", PayloadSchemaType.KEYWORD),   # filter by text/table/block
            ("language", PayloadSchemaType.KEYWORD),     # filter by language (future use)
            ("created_ts", PayloadSchemaType.INTEGER),   # sort/filter by creation time
        ]:
            try:
                self.qdrant.create_payload_index(
                    collection_name=settings.qdrant_collection,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception as e:
                logger.warning(f"Could not create payload index for {field_name}: {e}")

        return True  # collection was created — caller should re-embed all chunks

    def embed_text(self, text: str) -> dict:
        """
        Produce dense and sparse vectors for a single text string.

        Used by the RAG query path to embed the user's question before searching.

        Returns:
            Dict with "dense" (list of 1024 floats) and "sparse" (dict with
            "indices" and "values" lists — the sparse vector in coordinate format).
        """
        model = get_embedding_model()
        output = model.encode([text], return_dense=True, return_sparse=True)
        dense = output['dense_vecs'][0].tolist()
        # lexical_weights is a dict {token_id_str: weight_float} for the sparse vector
        sparse_weights = output['lexical_weights'][0]
        indices = [int(k) for k in sparse_weights.keys()]
        values = [float(v) for v in sparse_weights.values()]
        return {"dense": dense, "sparse": {"indices": indices, "values": values}}

    def embed_chunks(self, db: Session, document_id: str):
        """
        Embed all un-embedded chunks for a document and upsert them into Qdrant.

        Called by the embedding worker after the ingest pipeline creates chunks.
        Chunks in "pending" or "failed" status are embedded in one batch call
        (BGE-M3 is significantly faster batching than calling per-chunk).

        The Postgres fields updated after success:
        - is_embedded: True (legacy field for backward compatibility)
        - embedding_status: "done"
        - embedded_at: timestamp
        - qdrant_sync_status: "synced"
        - embedding_error: None (clear any previous error message)

        Args:
            db: Active database session.
            document_id: UUID of the Document whose chunks should be embedded.
        """
        # Only process chunks that haven't been embedded yet (or failed previously)
        chunks = (
            db.query(Chunk)
            .filter(
                Chunk.document_id == document_id,
                Chunk.embedding_status.in_(['pending', 'failed'])
            )
            .all()
        )
        if not chunks:
            logger.info(f"No unembedded chunks for document {document_id}")
            return

        # Mark as in_progress before starting — if the worker crashes mid-batch,
        # the healing job (SyncService) will detect these and requeue them.
        for chunk in chunks:
            chunk.embedding_status = 'in_progress'
            chunk.retry_count += 1
        db.commit()

        logger.info(f"Embedding {len(chunks)} chunks for document {document_id}")
        model = get_embedding_model()
        texts = [chunk.text for chunk in chunks]

        # Batch encode all chunks at once — BGE-M3 is GPU-accelerated and much
        # faster processing a list of texts than calling encode() per text.
        output = model.encode(texts, return_dense=True, return_sparse=True)
        dense_vecs = output['dense_vecs']           # shape: (len(chunks), 1024)
        sparse_weights_list = output['lexical_weights']  # list of {token_id: weight} dicts

        # Fetch source_id for use in the Qdrant payload (for filtered search)
        from models import Document
        doc = db.query(Document).filter(Document.id == document_id).first()
        source_id = doc.source_id if doc else None

        t0 = time.time()
        points = []
        for chunk, dense_vec, sparse_weights in zip(chunks, dense_vecs, sparse_weights_list):
            indices = [int(k) for k in sparse_weights.keys()]
            values = [float(v) for v in sparse_weights.values()]
            point = PointStruct(
                # Qdrant point IDs must be UUIDs or unsigned integers.
                # chunk.id is already a UUID string; ensure it's in the correct format.
                id=str(uuid.UUID(chunk.id)) if "-" in chunk.id else chunk.id,
                vector={
                    "dense": dense_vec.tolist(),  # 1024-float cosine vector
                    "sparse": SparseVector(indices=indices, values=values),
                },
                payload={
                    # Payload is stored alongside the vector for filtered retrieval.
                    # We store IDs here but NOT the chunk text (Postgres holds the text).
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
            # upsert: insert new points OR overwrite existing ones with the same ID.
            # Safe to run multiple times (idempotent).
            self.qdrant.upsert(collection_name=settings.qdrant_collection, points=points)
        except Exception as e:
            logger.error("Failed to upsert embeddings into Qdrant", extra={
                "event": "embedding_failed",
                "document_id": document_id,
                "chunk_count": len(chunks),
                "reason": str(e),
            })
            raise  # bubble up so the worker marks the job as failed

        elapsed = time.time() - t0
        now = datetime.utcnow()
        # Update all chunks in one batch commit after successful Qdrant upsert
        for chunk in chunks:
            chunk.is_embedded = True          # legacy boolean field
            chunk.embedding_status = 'done'
            chunk.embedded_at = now
            chunk.qdrant_sync_status = 'synced'
            chunk.qdrant_synced_at = now
            chunk.embedding_error = None      # clear any previous error message
        db.commit()

        # Record Prometheus metrics for the embedding pipeline dashboard
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
        Hybrid semantic + keyword search: dense + sparse prefetch, fused with RRF.

        How it works:
        1. Embed the query with BGE-M3 to get a dense vector and sparse weights.
        2. Ask Qdrant to find the 50 most similar dense vectors AND the 50 most
           similar sparse vectors separately (two "prefetch" queries).
        3. Qdrant fuses both ranked lists using RRF (Reciprocal Rank Fusion):
           a chunk that ranks well in both lists gets a high combined score.
        4. Fetch the actual chunk text from Postgres by chunk_id (one IN query).
        5. Drop any Qdrant hits whose chunk_id is missing from Postgres (stale
           vectors from a DB reset), and optionally self-heal by deleting them.

        Args:
            query: The natural-language search string (user's question).
            top_k: Number of results to return after fusion and filtering.
            source_id: Optional UUID to restrict search to one source's chunks.
            db: Optional DB session for fetching chunk text and self-healing.

        Returns:
            List of dicts with keys: chunk_id, document_id, text, citation_url, score.
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

            # Build an optional filter to restrict search to a single source
            search_filter = None
            if source_id:
                search_filter = Filter(
                    must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
                )

            # Fetch more candidates than top_k so we have room to drop stale vectors
            candidate_limit = max(top_k * 5, 20)
            results = self.qdrant.query_points(
                collection_name=settings.qdrant_collection,
                prefetch=[
                    # Dense prefetch: find the 50 nearest cosine-neighbours
                    Prefetch(
                        query=dense_vec,
                        using="dense",
                        limit=50,
                        filter=search_filter,
                    ),
                    # Sparse prefetch: find the 50 highest keyword-overlap matches
                    Prefetch(
                        query=SparseVector(indices=sparse_indices, values=sparse_values),
                        using="sparse",
                        limit=50,
                        filter=search_filter,
                    ),
                ],
                # RRF (Reciprocal Rank Fusion): merge the two ranked lists by summing
                # 1/(rank+60) for each item across both lists. Items appearing in both
                # lists get a higher combined score than items in only one list.
                query=FusionQuery(fusion=Fusion.RRF),
                limit=candidate_limit,
                with_payload=True,  # return the chunk_id / source_id payload with each hit
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

        # Batch-fetch chunk text from Postgres using a single IN query
        chunk_ids = [h.payload.get("chunk_id") for h in hits if h.payload.get("chunk_id")]
        chunk_text_map = {}
        if chunk_ids and db is not None:
            rows = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
            chunk_text_map = {r.id: r.text for r in rows}
            # Detect stale Qdrant vectors: IDs returned by Qdrant but not in Postgres
            stale_ids = [cid for cid in chunk_ids if cid and cid not in chunk_text_map]
            if stale_ids:
                # Best-effort self-heal: delete orphaned vectors from Qdrant.
                # These accumulate when the Postgres DB is reset but Qdrant persists.
                try:
                    self.delete_chunks(stale_ids)
                    logger.warning(
                        "Deleted %d stale vectors with missing chunk rows",
                        len(stale_ids),
                        extra={"event": "chunks_delete", "count": len(stale_ids)},
                    )
                except Exception as e:
                    logger.warning("Failed to delete stale vectors: %s", e)

        logger.info("Qdrant search complete", extra={
            "event": "search_complete",
            "hits": len(hits),
            "top_k": top_k,
            "elapsed_ms": round((time.time() - t0) * 1000),
        })

        # Build result list, skipping any hits whose text is missing (stale vectors)
        filtered = []
        for h in hits:
            chunk_id = h.payload.get("chunk_id")
            text = chunk_text_map.get(chunk_id, "")
            if not text:
                continue  # skip — no Postgres row for this vector
            filtered.append({
                "chunk_id": chunk_id,
                "document_id": h.payload.get("document_id"),
                "text": text,
                "citation_url": h.payload.get("citation_url"),
                "score": h.score,  # RRF fusion score (higher is better)
            })
            if len(filtered) >= top_k:
                break  # stop once we have enough results
        return filtered

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        """
        Remove Qdrant points whose payload chunk_id matches any of the given UUIDs.

        Used when chunks are deleted from Postgres (to keep Qdrant in sync) and
        when self-healing detects orphaned vectors after a DB reset.

        Args:
            chunk_ids: List of chunk UUID strings to remove.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        if not chunk_ids:
            return
        logger.info("Deleting %d chunks from Qdrant", len(chunk_ids), extra={
            "event": "chunks_delete",
            "count": len(chunk_ids),
        })
        # Delete all points where the "chunk_id" payload field matches any of the IDs
        self.qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=Filter(
                must=[FieldCondition(key="chunk_id", match=MatchAny(any=chunk_ids))]
            ),
        )

    def reconcile_with_db(self, db: Session) -> None:
        """
        Detect and recover from a full DB/PVC reset where Postgres lost all rows
        but Qdrant still has vectors from the previous state.

        When this happens, every search returns Qdrant hits with no matching
        Postgres row, causing all queries to return empty results.
        The fix is to drop the stale Qdrant collection and recreate it empty.

        This method is called at startup from main.py. It is a no-op if Postgres
        has any chunk rows (the normal case).

        Args:
            db: Active database session.
        """
        db_chunk_count = db.query(func.count(Chunk.id)).scalar() or 0
        if db_chunk_count != 0:
            return  # DB has chunks — no drift to fix

        try:
            qdrant_count = self.qdrant.count(
                collection_name=settings.qdrant_collection,
                exact=False,  # approximate count is fast; exact=True would lock the collection
            ).count
        except Exception:
            return  # can't reach Qdrant — skip reconciliation

        if qdrant_count > 0:
            # DB is empty but Qdrant still has points → full orphan state
            logger.warning(
                "Detected %d orphaned Qdrant points with empty DB; recreating collection",
                qdrant_count,
            )
            self.qdrant.delete_collection(settings.qdrant_collection)
            self._ensure_collection()
