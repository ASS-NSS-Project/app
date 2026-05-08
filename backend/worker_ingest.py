"""
worker_ingest.py - Background ingest job processor

Runs as a separate Docker/Kubernetes container (not as part of the API process).
Connects to RabbitMQ, picks up ingest job messages one at a time, and runs the
full scraping pipeline for each job.

Restaurant analogy:
  API (waiter): takes the order and puts a ticket on the pass
  Worker (kitchen): picks up the ticket and cooks the meal

Why a separate process?
Scraping a URL can take 30–60 seconds (browser launch, JS render, VLM call).
If we ran this inside the API request handler, every ingest trigger would block
for up to a minute, exhausting the API's connection pool and making the UI
unresponsive. The RabbitMQ queue decouples the trigger from the execution:
the API returns immediately with a job_id, and the worker processes it in the background.

RabbitMQ delivery semantics:
- prefetch_count=1: the worker processes one job at a time to avoid OOM from
  concurrent BGE-M3 inference.
- basic_ack: sent after successful processing so RabbitMQ removes the message.
- basic_nack(requeue=True): sent on unexpected errors so RabbitMQ re-delivers
  the message (another worker picks it up, or this one retries after a restart).
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
from services.ingest import IngestService
from services.embedding import EmbeddingService, get_embedding_model
from services.logging_config import setup_logging
from services.queue import INGEST_QUEUE, wait_for_rabbitmq

# Set up structured JSON logging before anything else imports 'logging'.
# This must happen first — see logging_config.py for why order matters.
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)
settings = get_settings()


def process_ingest_job(job_id: str) -> None:
    """
    Process a single ingest job end-to-end.

    Steps:
    1. Load the job from Postgres and apply state-gate logic for redelivered messages.
    2. Run the ingest pipeline (scraping → text extraction → chunking → DB write).
    3. If ingest succeeded: publish an embedding job to the "embeddings" queue.
    4. Stamp last_crawled_at on the source regardless of outcome, so the scheduler
       does not immediately re-queue the same source on the next 5-minute tick.

    State gate logic for redelivered messages (RabbitMQ re-delivers when the
    previous consumer crashed before acknowledging):
    - status=done: ingest completed but the embedding queue publish may have failed.
      Recovery: re-try the embedding step.
    - status=failed or captcha_blocked: terminal state. Skip (noop) — re-ingesting
      would produce the same result.
    - status=running: the previous worker crashed mid-ingest. Restart from scratch.
    - status=pending: normal first delivery.

    Args:
        job_id: UUID string of the IngestJob row to process.
    """
    logger.info("Worker picked up job", extra={"event": "worker_job_started", "job_id": job_id})
    db = SessionLocal()

    # Pre-flight state check — handles redelivered messages after worker crashes
    preflight = db.query(IngestJob).filter(IngestJob.id == job_id).first()
    if not preflight:
        # Job was deleted or never existed (race condition with a cancel)
        logger.info("Job already cancelled or missing, skipping", extra={
            "event": "worker_job_skipped", "job_id": job_id,
        })
        db.close()
        return

    if preflight.status == JobStatus.done:
        # Ingest completed, but the worker crashed before publishing the embedding job.
        # Skip re-scraping; just re-trigger the embedding step.
        logger.info("Recovering done job: retrying embedding step", extra={
            "event": "worker_job_recovery_embedding",
            "job_id": job_id,
            "source_id": str(preflight.source_id),
        })
        try:
            _embed_job_chunks(db, preflight)
        finally:
            db.close()
        return

    if preflight.status in (JobStatus.failed, JobStatus.captcha_blocked):
        # Terminal states — re-running would produce the same outcome
        logger.info("Job in terminal state, skipping", extra={
            "event": "worker_job_skipped",
            "job_id": job_id,
            "status": preflight.status.value,
        })
        db.close()
        return

    try:
        if preflight.status == JobStatus.running:
            # The previous worker was OOM-killed or crashed while processing this job.
            # Restart the ingest from scratch (simpler than resuming mid-pipeline).
            logger.info("Recovering running job after worker interruption", extra={
                "event": "worker_job_recovery_running",
                "job_id": job_id,
                "source_id": str(preflight.source_id),
            })

        # asyncio.run() creates a fresh event loop for each job.
        # pika (our RabbitMQ client) is synchronous and doesn't play well with
        # a persistent async event loop — a new loop per job avoids stale coroutines.
        ingest_service = IngestService(db)
        job = asyncio.run(ingest_service.run(job_id))

        if job.status == JobStatus.done:
            # Ingest succeeded — publish an embedding job so chunks get vectorised
            _queue_embedding_job(db, job)
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

        # Always update last_crawled_at regardless of outcome.
        # Without this, a captcha_blocked or failed job would cause the scheduler
        # to re-queue the source every 5 minutes (since last_crawled_at + frequency
        # would still be in the past).
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
        # Mark the job failed so it doesn't remain in "running" state indefinitely
        failed_job = db.query(IngestJob).filter(IngestJob.id == job_id).first()
        if failed_job:
            failed_job.status = JobStatus.failed
            failed_job.error_message = str(e)
            db.commit()
    finally:
        db.close()  # always release the DB connection back to the pool


def _queue_embedding_job(db, job: IngestJob) -> None:
    """
    Publish an embedding job for the document created by this ingest job.

    The ingest pipeline creates a Document row; we need its ID to publish
    the embedding job. We find the most recently versioned document for the
    same source + URL (the one this ingest job just created).

    Decoupling ingest from embedding means the API responds to ingest triggers
    immediately, and embedding happens asynchronously. This prevents OOM kills
    when BGE-M3 is already loaded in the embed worker and ingest would double up.

    Args:
        db: Active database session.
        job: The completed IngestJob.
    """
    from models import Document
    from services.queue import publish_embedding_job

    # Get the most recently versioned document for this job's URL
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

    # Publish a normal-priority embedding job (healing jobs use 'high' or 'low')
    publish_embedding_job(doc.id, priority='normal')
    logger.info(
        "Queued document for embedding",
        extra={
            "event": "embedding_queued",
            "document_id": doc.id,
            "job_id": job.id
        }
    )


def _embed_job_chunks(db, job: IngestJob) -> None:
    """
    Recovery helper: re-queue the embedding step for a job that already finished ingest.

    Called when a redelivered message arrives for a job that is already "done"
    in Postgres. The ingest was successful but the embedding publish may have
    failed before the job was acknowledged. We re-trigger embedding only.

    Args:
        db: Active database session.
        job: The IngestJob in "done" status.
    """
    _queue_embedding_job(db, job)


def on_message(channel, method, _properties, body: bytes) -> None:
    """
    Callback invoked by pika for each incoming RabbitMQ message.

    pika calls this function synchronously inside the blocking consumer loop.
    We parse the JSON payload, extract the job_id, and call process_ingest_job().

    Acknowledgement rules:
    - basic_ack: message processed successfully — RabbitMQ removes it from the queue.
    - basic_nack(requeue=False): malformed message — discard it (prevents a poison pill
      from being redelivered forever).
    - basic_nack(requeue=True): unexpected exception — put back in queue for retry.

    Args:
        channel: pika channel (used to ack/nack).
        method: Delivery metadata (contains delivery_tag for ack/nack).
        _properties: Message properties (unused).
        body: Raw message bytes (JSON-encoded).
    """
    try:
        payload = json.loads(body)
        job_id = payload["job_id"]
    except (json.JSONDecodeError, KeyError) as e:
        # Malformed message — don't requeue (it would loop forever)
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
        # Requeue so another worker can pick it up
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


if __name__ == "__main__":
    logger.info("Starting RAG ingest worker", extra={"event": "startup"})

    # Expose a Prometheus /metrics endpoint on port 9090 (scraped by Kubernetes PodMonitor)
    metrics_port = int(os.getenv("WORKER_METRICS_PORT", "9090"))
    start_http_server(metrics_port)
    logger.info("Prometheus metrics server started on port %d", metrics_port)

    # Load BGE-M3 model weights before starting the consumer loop.
    # The first load downloads ~2.3 GB from HuggingFace Hub (if not cached).
    # Pre-loading here prevents an OOM kill mid-job when the first embedding
    # job arrives right after a fresh worker start.
    get_embedding_model()

    # Retry until RabbitMQ is accepting connections
    # (handles the race where Kubernetes starts the worker before RabbitMQ is ready)
    wait_for_rabbitmq()

    # Open a persistent AMQP connection to RabbitMQ
    params = pika.URLParameters(settings.rabbitmq_url)
    # Heartbeat 600 s: RabbitMQ closes idle connections after 60 s by default.
    # We need a much longer timeout because BGE-M3 model download on first boot
    # can take several minutes, and a browser + VLM ingest job can take 60+ s.
    params.heartbeat = 600
    params.blocked_connection_timeout = 300
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # Declare the queue (idempotent — no-op if it already exists with same settings)
    channel.queue_declare(queue=INGEST_QUEUE, durable=True)

    # prefetch_count=1: receive one message at a time, don't prefetch the next one
    # until the current one is acknowledged. This implements "fair dispatch" —
    # the worker only gets the next job when it's truly finished with the current one.
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=INGEST_QUEUE, on_message_callback=on_message)

    logger.info(f"Worker ready. Listening on queue: {INGEST_QUEUE}")
    # start_consuming() enters a blocking I/O loop — it never returns unless interrupted
    channel.start_consuming()
