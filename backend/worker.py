"""
worker.py - Background ingest job processor

Runs as a separate Docker container.
Listens to the "ingest" queue in RabbitMQ and processes scraping jobs.

Restaurant analogy:
- API (waiter): takes the order and puts a ticket in the queue
- Worker (kitchen): picks up the ticket and prepares the meal

Why a separate process?
Scraping a single URL can take 30–60 seconds. We don't want to block
the API while it waits for results. The queue decouples this.
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime

import pika
from prometheus_client import start_http_server

from config import get_settings
from database import SessionLocal
from models import IngestJob, JobStatus, Source
from services.ingest_service import IngestService
from services.embedding_service import EmbeddingService, get_embedding_model
from services.logging_config import setup_logging
from services.queue_service import QUEUE_NAME, wait_for_rabbitmq

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
settings = get_settings()


def process_ingest_job(job_id: str) -> None:
    """
    Processes a single ingest job:
    1. Runs the ingest pipeline (scraping → extraction → save to DB and MinIO)
    2. Embeds chunks into Qdrant
    3. Updates last_crawled_at on the source (for the scheduler)

    Synchronous wrapper around async code – pika doesn't natively support async.
    """
    logger.info("Worker picked up job", extra={"event": "worker_job_started", "job_id": job_id})
    db = SessionLocal()

    # Job may have been cancelled between being queued and picked up
    preflight = db.query(IngestJob).filter(IngestJob.id == job_id).first()
    if not preflight or preflight.status != JobStatus.pending:
        logger.info("Job already cancelled or missing, skipping", extra={
            "event": "worker_job_skipped", "job_id": job_id,
        })
        db.close()
        return

    try:
        ingest_service = IngestService(db)
        job = asyncio.run(ingest_service.run(job_id))

        if job.status == JobStatus.done:
            _embed_job_chunks(db, job)
            logger.info("Worker job fully processed", extra={
                "event": "worker_job_completed",
                "job_id": job_id,
                "source_id": str(job.source_id),
            })
        else:
            logger.warning("Worker job finished with non-done status", extra={
                "event": "worker_job_incomplete",
                "job_id": job_id,
                "status": job.status.value,
            })

        # Always stamp last_crawled_at regardless of outcome — without this the
        # scheduler would re-queue the source every 5 minutes whenever a job
        # ends as captcha_blocked or failed.
        source = db.query(Source).filter(Source.id == job.source_id).first()
        if source:
            source.last_crawled_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        logger.exception("Worker job crashed", extra={
            "event": "worker_job_crashed",
            "job_id": job_id,
            "reason": str(e),
        })
        failed_job = db.query(IngestJob).filter(IngestJob.id == job_id).first()
        if failed_job:
            failed_job.status = JobStatus.failed
            failed_job.error_message = str(e)
            db.commit()
    finally:
        db.close()


def _embed_job_chunks(db, job: IngestJob) -> None:
    """
    After a successful ingest, finds the document created by this job
    and embeds its chunks into Qdrant.
    """
    from models import Document

    doc = (
        db.query(Document)
        .filter(
            Document.source_id == job.source_id,
            Document.url == job.url,
        )
        .order_by(Document.doc_version.desc())
        .first()
    )

    if not doc:
        logger.warning(f"No document found for job {job.id} / URL {job.url}")
        return

    embedder = EmbeddingService()
    embedder.embed_chunks(db, doc.id)


def on_message(channel, method, _properties, body: bytes) -> None:
    """
    Callback invoked by RabbitMQ for each incoming message.

    After successful processing we acknowledge the message (basic_ack).
    If processing fails, the message is returned to the queue (basic_nack).
    """
    try:
        payload = json.loads(body)
        job_id = payload["job_id"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Invalid message in queue, dropping", extra={
            "event": "worker_invalid_message",
            "reason": str(e),
        })
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        process_ingest_job(job_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.exception("Unexpected error processing job, requeueing", extra={
            "event": "worker_job_crashed",
            "job_id": job_id,
            "reason": str(e),
        })
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


if __name__ == "__main__":
    logger.info("Starting RAG ingest worker", extra={"event": "startup"})

    # Expose Prometheus metrics on port 9090 (scraped by PodMonitor)
    metrics_port = int(os.getenv("WORKER_METRICS_PORT", "9090"))
    start_http_server(metrics_port)
    logger.info("Prometheus metrics server started on port %d", metrics_port)

    # Load BGE-M3 weights before consuming — prevents OOMKill on first embed job
    get_embedding_model()

    # Wait until RabbitMQ is available
    wait_for_rabbitmq()

    # Connect to RabbitMQ and start the consumer loop
    params = pika.URLParameters(settings.rabbitmq_url)
    # Heartbeat 600 s – prevents disconnection during long-running tasks
    # (e.g. first download of the embedding model can take several minutes)
    params.heartbeat = 600
    params.blocked_connection_timeout = 300
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # Declare the queue (idempotent – no-op if it already exists)
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    # Process one message at a time (fair dispatch)
    # The worker won't receive the next message until it acknowledges the current one
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)

    logger.info(f"Worker ready. Listening on queue: {QUEUE_NAME}")
    channel.start_consuming()
