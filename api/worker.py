"""
worker.py - Background Job Processor

This runs as a separate process (the "worker" container in Docker Compose).
It watches the Redis "ingest" queue and processes scraping jobs.

Think of it like a restaurant kitchen:
- The API (waiter) takes orders and puts them in a ticket queue
- The Worker (kitchen) picks up tickets and makes the food

Why separate? Because scraping can take 30-60 seconds per URL.
We can't block the API while waiting. The queue decouples them.

RQ (Redis Queue) is the library that handles this pattern.
"""

import asyncio
import logging
import os
import time

import redis
from rq import Worker, Queue, Connection
from sqlalchemy.orm import Session

from config import get_settings
from database import SessionLocal
from models import IngestJob, JobStatus
from services.ingest_service import IngestService
from services.embedding_service import EmbeddingService
from services.auth_service import log_action

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


def process_ingest_job(job_id: str):
    """
    This function is called by RQ when a job is dequeued.
    
    It:
    1. Runs the ingest pipeline (scrape → extract → store)
    2. Embeds the resulting chunks into Qdrant
    
    This runs synchronously (RQ doesn't support async natively),
    so we use asyncio.run() to run async code inside it.
    """
    logger.info(f"Worker picked up job: {job_id}")
    db = SessionLocal()

    try:
        # Run the async ingest pipeline synchronously
        ingest_service = IngestService(db)
        job = asyncio.run(ingest_service.run(job_id))

        # If ingest succeeded, embed the chunks
        if job.status == JobStatus.done:
            logger.info(f"Job {job_id} done, starting embedding...")
            _embed_job_chunks(db, job)
            logger.info(f"Job {job_id} fully processed (ingest + embed)")
        else:
            logger.warning(f"Job {job_id} finished with status: {job.status}")

    except Exception as e:
        logger.exception(f"Worker failed processing job {job_id}: {e}")
        # Mark the job as failed in DB
        job = db.query(IngestJob).filter(IngestJob.id == job_id).first()
        if job:
            job.status = JobStatus.failed
            job.error_message = str(e)
            db.commit()
    finally:
        db.close()


def _embed_job_chunks(db: Session, job: IngestJob):
    """
    After ingest, find the document created by this job and embed its chunks.
    """
    from models import Document

    # Find documents created for this job's URL (most recent version)
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


def wait_for_redis(max_retries: int = 30, delay: float = 2.0):
    """
    Wait until Redis is available before starting the worker.
    Docker containers can start in any order, so Redis might not be ready yet.
    """
    redis_conn = redis.from_url(settings.redis_url)
    for attempt in range(max_retries):
        try:
            redis_conn.ping()
            logger.info("Redis connection established")
            return redis_conn
        except Exception as e:
            logger.info(f"Waiting for Redis (attempt {attempt + 1}/{max_retries})...")
            time.sleep(delay)
    raise RuntimeError("Could not connect to Redis after retries")


if __name__ == "__main__":
    """
    Entry point: start the RQ worker.
    
    The worker listens on the "ingest" queue.
    When a job arrives, it calls process_ingest_job(job_id).
    """
    logger.info("Starting RAG ingest worker...")

    # Wait for Redis to be ready
    redis_conn = wait_for_redis()

    # Start the RQ worker
    # It runs forever, processing jobs as they arrive
    with Connection(redis_conn):
        worker = Worker(
            queues=["ingest"],
            connection=redis_conn,
        )
        logger.info("Worker ready. Listening on queue: ingest")
        worker.work(with_scheduler=True)
