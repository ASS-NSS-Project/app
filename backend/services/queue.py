"""
services/queue_service.py - RabbitMQ integration

Provides helper functions for publishing messages to the "ingest" queue
and waiting for RabbitMQ to become available.

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

# Queue name – must match between the API (publisher) and the worker (consumer)
QUEUE_NAME = "ingest"


def _get_connection() -> pika.BlockingConnection:
    """Creates a new synchronous connection to RabbitMQ."""
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 60
    return pika.BlockingConnection(params)


def publish_job(job_id: str) -> None:
    """
    Publishes a job ID to the RabbitMQ queue.

    The worker picks up the message and calls process_ingest_job(job_id).
    The queue is durable (durable=True) and messages are persistent (delivery_mode=2),
    so a RabbitMQ restart won't lose pending jobs.
    """
    connection = _get_connection()
    try:
        channel = connection.channel()
        # Declare the queue – if it already exists this is a no-op
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"job_id": job_id}),
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent message (survives broker restart)
            ),
        )
        logger.info(f"Job {job_id} published to queue '{QUEUE_NAME}'")
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
