"""
services/queue.py - RabbitMQ Message Queue Integration

Provides two publish functions for sending work to background workers:
- publish_job(): sends an ingest job ID to the "ingest" queue
- publish_embedding_job(): sends a document ID to the "embeddings" queue

Why RabbitMQ instead of calling the worker directly?
- Decoupling: the API returns immediately; the worker processes in the background.
  A scrape job can take 30–60 seconds — we cannot block the HTTP request that long.
- Durability: messages survive a RabbitMQ restart (durable queue + persistent delivery).
  If the worker crashes mid-job, the unacknowledged message returns to the queue.
- Backpressure: the worker processes one message at a time (prefetch_count=1).
  The queue absorbs bursts without overloading the worker.

Queue names are constants so publishers and consumers always agree on the name.
"""

import json
import logging
import time

import pika

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Queue names — shared between publishers (API) and consumers (workers).
# Changing these requires restarting both the API and the workers.
INGEST_QUEUE    = "ingest"
EMBEDDING_QUEUE = "embeddings"


def _get_connection() -> pika.BlockingConnection:
    """
    Open a new synchronous AMQP connection to RabbitMQ.

    Each publish call opens and immediately closes its own connection.
    This is intentionally simple — connection pooling would add complexity
    for the low publish rate this system expects (<1 msg/s on average).

    Returns:
        An open pika BlockingConnection.
    """
    params = pika.URLParameters(settings.rabbitmq_url)
    # 60 s heartbeat: RabbitMQ closes idle connections after 60 s without one.
    # Publishers connect, send one message, and close — so 60 s is plenty.
    params.heartbeat = 60
    return pika.BlockingConnection(params)


def publish_job(job_id: str) -> None:
    """
    Publish an ingest job ID to the "ingest" queue.

    The ingest worker picks up the message and calls process_ingest_job(job_id).

    Queue settings:
    - durable=True: the queue definition survives a RabbitMQ restart.
    - delivery_mode=2: the message itself is written to disk before RabbitMQ
      confirms receipt, so it survives a broker restart too.
    - queue_declare is idempotent: safe to call on every publish — if the queue
      already exists with the same parameters, it's a no-op.

    Args:
        job_id: UUID of the IngestJob row to process.
    """
    connection = _get_connection()
    try:
        channel = connection.channel()
        # Declare the queue (creates it if it doesn't exist yet)
        channel.queue_declare(queue=INGEST_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",           # Default exchange — routes directly to the named queue
            routing_key=INGEST_QUEUE,
            body=json.dumps({"job_id": job_id}),
            properties=pika.BasicProperties(
                delivery_mode=2,   # Persistent: survive broker restart
            ),
        )
        logger.info("Ingest job published", extra={"event": "ingest_job_published", "job_id": job_id})
    finally:
        connection.close()


def publish_embedding_job(document_id: str, priority: str = 'normal') -> None:
    """
    Publish an embedding job to the "embeddings" queue.

    The embed worker picks up the message and calls process_embedding_job(document_id).

    The `priority` field is informational — the embed worker logs it but does not
    actually implement queue-level priority ordering (all messages are FIFO).
    It exists so that healing jobs can be distinguished from normal ingest-triggered
    jobs in logs and metrics.

    Args:
        document_id: UUID of the Document whose chunks should be embedded.
        priority: 'high' (manual re-embed), 'normal' (post-ingest), 'low' (healing job).
    """
    connection = _get_connection()
    try:
        channel = connection.channel()
        channel.queue_declare(queue=EMBEDDING_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=EMBEDDING_QUEUE,
            body=json.dumps({
                "document_id": document_id,
                "priority": priority,
                "retry_count": 0,   # Incremented by the worker on each requeue
            }),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        logger.info("Embedding job published", extra={
            "event": "embedding_job_published",
            "document_id": document_id,
            "priority": priority,
        })
    finally:
        connection.close()


def wait_for_rabbitmq(max_retries: int = 30, delay: float = 2.0) -> None:
    """
    Block until a RabbitMQ connection can be established.

    Called at worker startup to handle the race condition where the worker
    container starts before RabbitMQ is ready (common in Docker Compose and
    Kubernetes when there's no readiness gate between them).

    Args:
        max_retries: How many connection attempts before giving up and crashing.
        delay: Seconds to wait between attempts.

    Raises:
        RuntimeError: If RabbitMQ is still unreachable after max_retries attempts.
    """
    for attempt in range(max_retries):
        try:
            conn = _get_connection()
            conn.close()
            logger.info("Connected to RabbitMQ successfully")
            return
        except Exception:
            logger.info(f"Waiting for RabbitMQ (attempt {attempt + 1}/{max_retries})...")
            time.sleep(delay)

    raise RuntimeError("Failed to connect to RabbitMQ after repeated attempts")
