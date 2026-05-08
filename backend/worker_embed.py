"""
worker_embed.py - Background embedding job processor

Runs as a separate process (Kubernetes Deployment with a different command).
Listens to the "embeddings" queue in RabbitMQ and embeds document chunks
into Qdrant using BGE-M3 (BAAI/bge-m3) dense + sparse vectors.

Why decoupled from ingest?
The ingest worker scrapes and saves text to Postgres in ~30 seconds.
Embedding a full document with BGE-M3 takes 1–5 minutes depending on chunk count.
Keeping them separate means ingest is always fast and the queue never backs up
just because embedding is slow.

Retry strategy:
If process_embedding_job() raises, the message is nack'd and requeued.
The retry_count field in the message payload tracks how many attempts have
been made. After 3 failures, the message is acked (discarded) so a single
broken document doesn't loop forever. The SyncService healing job will detect
the failed chunks and retry them through a fresh message.
"""

import json
import logging
import os
from datetime import datetime

import pika
from prometheus_client import start_http_server
from qdrant_client.models import PointStruct, SparseVector

from config import get_settings
from database import SessionLocal
from models import Chunk, Document
from services.embedding import EmbeddingService, get_embedding_model
from services.logging_config import setup_logging
from services.queue import EMBEDDING_QUEUE, wait_for_rabbitmq
from services.storage import StorageService

# Set up structured JSON logging before anything else uses the logging module
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
settings = get_settings()


def process_embedding_job(document_id: str) -> None:
    """
    Embed all pending/failed chunks for a document and upsert them into Qdrant.

    Steps:
    1. Load the Document and its chunks with status "pending" or "failed".
    2. Mark chunks "in_progress" so the SyncService healing job can detect stalls.
    3. Batch-encode all chunk texts with BGE-M3 (dense + sparse vectors).
    4. Build Qdrant PointStruct objects for each chunk.
    5. Upsert all points to Qdrant in one call.
    6. Optionally back up raw vectors to S3 (if ENABLE_EMBEDDING_BACKUP_S3=true).
    7. Mark chunks "done", set timestamps, clear any previous error message.
    8. On failure: mark chunks "failed" with the error message for debugging.

    Args:
        document_id: UUID of the Document whose chunks should be embedded.

    Raises:
        Exception: On unrecoverable errors (caller nacks the RabbitMQ message).
    """
    db = SessionLocal()
    try:
        logger.info(
            "Processing embedding job",
            extra={"event": "embedding_job_started", "document_id": document_id}
        )

        # Load the document to get source_id for the Qdrant payload
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found")
            return  # not an error — document may have been deleted

        # Load only chunks that still need embedding (not already "done")
        chunks = (
            db.query(Chunk)
            .filter(
                Chunk.document_id == document_id,
                Chunk.embedding_status.in_(['pending', 'failed'])
            )
            .all()
        )

        if not chunks:
            logger.info(f"No chunks to embed for document {document_id}")
            return

        # Mark chunks in_progress before the batch encode.
        # If the worker is killed mid-encode, SyncService.heal_pending_embeddings()
        # will detect these after 10 minutes and requeue the document.
        for chunk in chunks:
            chunk.embedding_status = 'in_progress'
            chunk.retry_count += 1  # track total attempts for the healing job
        db.commit()

        logger.info(
            f"Embedding {len(chunks)} chunks",
            extra={
                "event": "embedding_started",
                "document_id": document_id,
                "chunk_count": len(chunks)
            }
        )

        # Create an EmbeddingService instance (connects to Qdrant, loads model singleton)
        embedder = EmbeddingService()
        texts = [c.text for c in chunks]

        # embed_text() returns {"dense": [...1024 floats], "sparse": {"indices": [...], "values": [...]}}
        # We embed one chunk at a time here; for better throughput the ingest worker
        # uses EmbeddingService.embed_chunks() which batches all texts in one model call.
        embeddings = []
        for text in texts:
            emb = embedder.embed_text(text)
            embeddings.append(emb)

        # Build one Qdrant PointStruct per chunk.
        # The "id" field must be a UUID string or unsigned integer — we use the chunk UUID.
        # The "payload" stores chunk metadata for filtered search (source_id, citation_url).
        points = []
        for chunk, emb in zip(chunks, embeddings):
            point = PointStruct(
                id=chunk.id,
                vector={
                    "dense": emb['dense'],  # 1024-float cosine similarity vector
                    "sparse": SparseVector(
                        indices=emb['sparse']['indices'],  # token IDs from vocabulary
                        values=emb['sparse']['values']     # weight per token
                    )
                },
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "source_id": doc.source_id,
                    "citation_url": chunk.citation_url,
                    # .value gives the string representation of the enum (e.g. "text", "table")
                    "chunk_type": chunk.chunk_type.value if hasattr(chunk.chunk_type, 'value') else str(chunk.chunk_type),
                    "language": chunk.language,
                    "created_ts": int(chunk.created_at.timestamp()) if chunk.created_at else 0
                }
            )
            points.append(point)

        # Upsert all points in one batch request.
        # wait=True: block until Qdrant confirms the write is durable.
        # This is safer than wait=False (fire-and-forget) which can lose data on restart.
        embedder.qdrant.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
            wait=True
        )

        logger.info(
            f"Upserted {len(points)} vectors to Qdrant",
            extra={
                "event": "qdrant_upsert_complete",
                "document_id": document_id,
                "point_count": len(points)
            }
        )

        # Optional S3 backup of raw embedding vectors for disaster recovery.
        # Disabled by default (ENABLE_EMBEDDING_BACKUP_S3=false) because storing
        # all vectors for a large index is expensive. Enable only if you need to
        # rebuild Qdrant from scratch without re-running BGE-M3 inference.
        if settings.enable_embedding_backup_s3:
            storage = StorageService()
            for chunk, emb in zip(chunks, embeddings):
                try:
                    embedding_uri = storage.store_embedding_backup(
                        chunk.id,
                        emb['dense'],
                        emb['sparse']['indices'],
                        emb['sparse']['values']
                    )
                    chunk.s3_embedding_uri = embedding_uri
                except Exception as e:
                    # Backup failure is non-fatal — the vector is already in Qdrant
                    logger.warning(f"Failed to backup embedding for chunk {chunk.id}: {e}")

        # Mark all chunks as successfully embedded
        now = datetime.utcnow()
        for chunk in chunks:
            chunk.embedding_status = 'done'
            chunk.embedded_at = now
            chunk.qdrant_sync_status = 'synced'    # tells SyncService it's in Qdrant
            chunk.qdrant_synced_at = now
            chunk.is_embedded = True               # legacy boolean field (kept for compat)
            chunk.embedding_error = None           # clear any previous error message

        db.commit()

        logger.info(
            f"Embedding job completed for document {document_id}",
            extra={
                "event": "embedding_job_completed",
                "document_id": document_id,
                "chunk_count": len(chunks)
            }
        )

    except Exception as e:
        logger.exception(
            f"Embedding job failed for document {document_id}",
            extra={
                "event": "embedding_job_failed",
                "document_id": document_id,
                "error": str(e)
            }
        )

        # Mark in_progress chunks as failed so healing jobs can find them
        try:
            failed_chunks = (
                db.query(Chunk)
                .filter(
                    Chunk.document_id == document_id,
                    Chunk.embedding_status == 'in_progress'
                )
                .all()
            )
            for chunk in failed_chunks:
                chunk.embedding_status = 'failed'
                chunk.embedding_error = str(e)[:500]  # truncate to fit in column
            db.commit()
        except Exception as commit_error:
            logger.error(f"Failed to mark chunks as failed: {commit_error}")

        raise  # bubble up so on_message() nacks the RabbitMQ message

    finally:
        db.close()


def on_message(channel, method, _properties, body: bytes) -> None:
    """
    Callback invoked by pika for each incoming RabbitMQ message.

    Parses the JSON payload to get the document_id and retry_count,
    then calls process_embedding_job(). Handles ack/nack based on outcome.

    Retry limit:
    - retry_count < 3: nack with requeue=True (message goes back to queue)
    - retry_count >= 3: ack (message discarded) — prevents infinite loops on
      permanently broken documents. The SyncService will detect failed chunks
      and can trigger a fresh job with retry_count=0 if needed.

    Args:
        channel: pika channel for ack/nack calls.
        method: Delivery metadata (contains delivery_tag).
        _properties: Message properties (unused).
        body: Raw JSON bytes from RabbitMQ.
    """
    try:
        payload = json.loads(body)
        document_id = payload["document_id"]
        retry_count = payload.get("retry_count", 0)  # 0 if not set (first delivery)
    except (json.JSONDecodeError, KeyError) as e:
        # Malformed message — ack to discard it (avoid infinite redelivery loop)
        logger.error(
            "Invalid message in embedding queue, dropping",
            extra={"event": "embedding_invalid_message", "reason": str(e)},
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        process_embedding_job(document_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.exception(
            "Unexpected error processing embedding job",
            extra={
                "event": "embedding_job_crashed",
                "document_id": document_id,
                "reason": str(e),
            }
        )

        if retry_count < 3:
            # Retry — put the message back in the queue
            logger.info(f"Requeueing embedding job (retry {retry_count + 1}/3)")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        else:
            # Giving up — ack to remove from queue; SyncService healing will handle it
            logger.error(f"Giving up on embedding job after 3 retries")
            channel.basic_ack(delivery_tag=method.delivery_tag)


if __name__ == "__main__":
    logger.info("Starting RAG embedding worker", extra={"event": "startup"})

    # Expose Prometheus metrics on port 9091 (different from the ingest worker's 9090)
    metrics_port = int(os.getenv("EMBEDDING_WORKER_METRICS_PORT", "9091"))
    start_http_server(metrics_port)
    logger.info(f"Prometheus metrics server started on port {metrics_port}")

    # Pre-load BGE-M3 before the consumer loop starts.
    # The model is ~2.3 GB in memory; loading on first job would temporarily spike
    # memory and risk OOM if a Kubernetes memory limit is set close to the base usage.
    logger.info("Loading BGE-M3 model...")
    get_embedding_model()
    logger.info("BGE-M3 model loaded successfully")

    # Block until RabbitMQ is reachable (Kubernetes race condition: worker may start first)
    wait_for_rabbitmq()

    # Establish a persistent AMQP connection
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 600              # 10-minute heartbeat to prevent idle disconnects
    params.blocked_connection_timeout = 300
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # Declare the queue (idempotent — safe to run even if queue already exists)
    channel.queue_declare(queue=EMBEDDING_QUEUE, durable=True)

    # One message at a time — prevents memory spikes from concurrent BGE-M3 inference
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=EMBEDDING_QUEUE, on_message_callback=on_message)

    logger.info(f"Embedding worker ready. Listening on queue: {EMBEDDING_QUEUE}")
    channel.start_consuming()
