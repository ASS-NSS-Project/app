"""
worker_embed.py - Background embedding job processor

Runs as a separate process (or thread in the same worker container).
Listens to the "embeddings" queue in RabbitMQ and embeds chunks into Qdrant.

This worker is decoupled from ingest — ingest completes in 30 seconds,
embedding happens asynchronously in 1-5 minutes.
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

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
settings = get_settings()


def process_embedding_job(document_id: str) -> None:
    """
    Embed all chunks for a document and upsert into Qdrant.

    Steps:
    1. Load chunks WHERE embedding_status IN ('pending', 'failed')
    2. Mark chunks as 'in_progress'
    3. Batch embed using BGE-M3
    4. Upsert to Qdrant
    5. Optional: backup embeddings to S3
    6. Mark chunks as 'done', set timestamps
    """
    db = SessionLocal()
    try:
        logger.info(
            "Processing embedding job",
            extra={
                "event": "embedding_job_started",
                "document_id": document_id
            }
        )

        # Load document
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found")
            return

        # Load chunks that need embedding
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

        # Mark chunks as in_progress
        for chunk in chunks:
            chunk.embedding_status = 'in_progress'
            chunk.retry_count += 1
        db.commit()

        logger.info(
            f"Embedding {len(chunks)} chunks",
            extra={
                "event": "embedding_started",
                "document_id": document_id,
                "chunk_count": len(chunks)
            }
        )

        # Batch embed using BGE-M3
        embedder = EmbeddingService()
        texts = [c.text for c in chunks]

        # Get dense + sparse embeddings
        embeddings = []
        for text in texts:
            emb = embedder.embed_text(text)
            embeddings.append(emb)

        # Build Qdrant points
        points = []
        for chunk, emb in zip(chunks, embeddings):
            point = PointStruct(
                id=chunk.id,
                vector={
                    "dense": emb['dense'],
                    "sparse": SparseVector(
                        indices=emb['sparse']['indices'],
                        values=emb['sparse']['values']
                    )
                },
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "source_id": doc.source_id,
                    "citation_url": chunk.citation_url,
                    "chunk_type": chunk.chunk_type.value if hasattr(chunk.chunk_type, 'value') else str(chunk.chunk_type),
                    "language": chunk.language,
                    "created_ts": int(chunk.created_at.timestamp()) if chunk.created_at else 0
                }
            )
            points.append(point)

        # Upsert to Qdrant
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

        # Optional: Backup embeddings to S3
        storage = StorageService()
        if settings.enable_embedding_backup_s3:
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
                    logger.warning(f"Failed to backup embedding for chunk {chunk.id}: {e}")

        # Mark chunks as done
        now = datetime.utcnow()
        for chunk in chunks:
            chunk.embedding_status = 'done'
            chunk.embedded_at = now
            chunk.qdrant_sync_status = 'synced'
            chunk.qdrant_synced_at = now
            chunk.is_embedded = True  # Legacy field, keep for compatibility
            chunk.embedding_error = None

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

        # Mark chunks as failed
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
                chunk.embedding_error = str(e)[:500]
            db.commit()
        except Exception as commit_error:
            logger.error(f"Failed to mark chunks as failed: {commit_error}")

        raise

    finally:
        db.close()


def on_message(channel, method, _properties, body: bytes) -> None:
    """
    Callback invoked by RabbitMQ for each incoming message.

    After successful processing we acknowledge the message (basic_ack).
    If processing fails, the message is requeued (basic_nack) up to 3 times.
    """
    try:
        payload = json.loads(body)
        document_id = payload["document_id"]
        retry_count = payload.get("retry_count", 0)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(
            "Invalid message in embedding queue, dropping",
            extra={
                "event": "embedding_invalid_message",
                "reason": str(e),
            }
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

        # Requeue if retry_count < 3
        if retry_count < 3:
            logger.info(f"Requeueing embedding job (retry {retry_count + 1}/3)")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        else:
            logger.error(f"Giving up on embedding job after 3 retries")
            channel.basic_ack(delivery_tag=method.delivery_tag)


if __name__ == "__main__":
    logger.info("Starting RAG embedding worker", extra={"event": "startup"})

    # Expose Prometheus metrics on port 9091 (different from ingest worker)
    metrics_port = int(os.getenv("EMBEDDING_WORKER_METRICS_PORT", "9091"))
    start_http_server(metrics_port)
    logger.info(f"Prometheus metrics server started on port {metrics_port}")

    # Load BGE-M3 weights before consuming — prevents OOMKill on first job
    logger.info("Loading BGE-M3 model...")
    get_embedding_model()
    logger.info("BGE-M3 model loaded successfully")

    # Wait until RabbitMQ is available
    wait_for_rabbitmq()

    # Connect to RabbitMQ and start the consumer loop
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 600  # 10 minutes
    params.blocked_connection_timeout = 300
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # Declare the queue (idempotent)
    channel.queue_declare(queue=EMBEDDING_QUEUE, durable=True)

    # Process one message at a time
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=EMBEDDING_QUEUE, on_message_callback=on_message)

    logger.info(f"Embedding worker ready. Listening on queue: {EMBEDDING_QUEUE}")
    channel.start_consuming()
