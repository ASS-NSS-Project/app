"""
services/queue_service.py - RabbitMQ integration

Provides helper functions for publishing messages to queues:
- "ingest" queue: scraping jobs
- "embeddings" queue: embedding jobs (async from ingest)

Why RabbitMQ?
- AMQP protocol: messages are acknowledged only after successful processing (ack)
- Durable queues: survive a RabbitMQ restart without losing messages
- Management UI: queue overview at http://localhost:15672
"""

import json
import logging
import time

import pika

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Queue names – must match between publishers and consumers
INGEST_QUEUE = "ingest"
EMBEDDING_QUEUE = "embeddings"


def _get_connection() -> pika.BlockingConnection:
    """Creates a new synchronous connection to RabbitMQ."""
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 60
    return pika.BlockingConnection(params)


def publish_job(job_id: str) -> None:
    """
    Publishes an ingest job ID to the "ingest" queue.

    The ingest worker picks up the message and calls process_ingest_job(job_id).
    The queue is durable (durable=True) and messages are persistent (delivery_mode=2),
    so a RabbitMQ restart won't lose pending jobs.
    """
    connection = _get_connection()
    try:
        channel = connection.channel()
        channel.queue_declare(queue=INGEST_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=INGEST_QUEUE,
            body=json.dumps({"job_id": job_id}),
            properties=pika.BasicProperties(
                delivery_mode=2,
            ),
        )
        logger.info(
            f"Ingest job published",
            extra={"event": "ingest_job_published", "job_id": job_id}
        )
    finally:
        connection.close()


def publish_embedding_job(document_id: str, priority: str = 'normal') -> None:
    """
    Publishes an embedding job to the "embeddings" queue.

    The embedding worker picks up the message and embeds all chunks for the document.

    Args:
        document_id: Document UUID
        priority: 'high' (stuck/manual) | 'normal' (regular) | 'low' (healing)
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
                "retry_count": 0
            }),
            properties=pika.BasicProperties(
                delivery_mode=2,
            ),
        )
        logger.info(
            f"Embedding job published",
            extra={
                "event": "embedding_job_published",
                "document_id": document_id,
                "priority": priority
            }
        )
    finally:
        connection.close()


def wait_for_rabbitmq(max_retries: int = 30, delay: float = 2.0) -> None:
    """
    Blocks until RabbitMQ becomes available.

    Docker containers start asynchronously – RabbitMQ may not yet be
    reachable when the worker starts.
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
