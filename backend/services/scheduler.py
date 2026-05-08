"""
services/scheduler.py - Automatic crawl scheduling and background maintenance

This module runs background tasks that keep the system healthy without any
manual intervention. All tasks run inside the same process as the FastAPI API
using APScheduler's async scheduler.

Scheduled tasks:

  1. _schedule_due_sources (every 5 minutes)
     Scans the sources table for active sources whose next crawl is overdue
     and creates an IngestJob for each one, publishing it to RabbitMQ.

  2. _cleanup_expired_evidence (every 24 hours, starts after 1 hour)
     Deletes evidence files (screenshots, HTML dumps) from S3 and removes
     their database rows when they exceed the source's retention_days_evidence.

  3. _cleanup_expired_index (every 24 hours, starts after 2 hours)
     Deletes documents and their chunks from Postgres and Qdrant when they
     exceed the source's retention_days_index.

  4. _refresh_gauges (every 5 minutes)
     Updates Prometheus Gauge metrics that reflect current DB state:
     active source count, open incident count, Qdrant collection size.

  5–8. Healing jobs via SyncService (every 5–30 minutes)
     Detect and fix drift between Postgres and Qdrant:
     - Requeue chunks stuck in "pending" for > 10 minutes
     - Retry failed embeddings (up to 3 attempts)
     - Detect when Postgres and Qdrant counts diverge by > threshold
     - Re-sync chunks that show "done" in Postgres but are missing from Qdrant

Note: When running 3 API replicas, all three run their own scheduler, which
causes duplicate jobs. A future improvement is to use a Postgres advisory lock
or a dedicated scheduler pod to prevent this duplication.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from botocore.exceptions import ClientError
from sqlalchemy import func, text

from config import get_settings
from database import SessionLocal
from models import Chunk, Document, Evidence, Incident, IncidentStatus, IngestJob, Source, JobStatus
from services.metrics import ACTIVE_SOURCES, OPEN_INCIDENTS, QDRANT_COLLECTION_SIZE
from services.queue import publish_job, publish_embedding_job
from services.storage import StorageService
from services.sync import SyncService

logger = logging.getLogger(__name__)
settings = get_settings()

# How often the scheduler checks for sources due for a crawl
CHECK_INTERVAL_MINUTES = 5

# How often expired evidence/index cleanup runs (once per day is sufficient)
CLEANUP_INTERVAL_HOURS = 24


def _schedule_due_sources() -> None:
    """
    Check all active sources and create ingest jobs for those that are due.

    A source is "due" when either:
    - It has never been crawled (last_crawled_at IS NULL), or
    - Its next scheduled crawl time has passed:
      last_crawled_at + crawl_frequency_hours <= now

    For each due source, this function:
    1. Creates an IngestJob row in Postgres with status "pending".
    2. Publishes the job_id to the RabbitMQ "ingest" queue.
    3. If publishing fails, marks the job as "failed" immediately.

    This is a synchronous function — APScheduler runs it in a thread pool so it
    does not block the async event loop while waiting for DB or network I/O.
    """
    db = SessionLocal()
    try:
        # Load all active sources (is_active=True means the curator has not paused them)
        sources = db.query(Source).filter(Source.is_active == True).all()
        now = datetime.utcnow()
        scheduled = 0

        for source in sources:
            # Determine whether this source's next crawl window has opened
            if source.last_crawled_at is None:
                due = True  # never crawled — schedule immediately
            else:
                due = now >= source.last_crawled_at + timedelta(hours=source.crawl_frequency_hours)

            if not due:
                continue  # not yet time for this source

            # Create a new IngestJob record so the worker has something to pick up
            job = IngestJob(
                source_id=source.id,
                url=source.base_url,
                status=JobStatus.pending,
            )
            db.add(job)
            db.commit()
            db.refresh(job)  # refresh to get the auto-generated UUID

            # Publish the job_id to RabbitMQ — the ingest worker consumes it
            try:
                publish_job(job.id)
                scheduled += 1
                logger.info("Crawl job scheduled", extra={
                    "event": "scheduler_job_triggered",
                    "source_id": source.id,
                    "source_name": source.name,
                    "job_id": job.id,
                    "url": source.base_url,
                })
            except Exception as e:
                # If RabbitMQ is down, mark the job failed immediately rather than
                # leaving it in "pending" where it would never be picked up
                job.status = JobStatus.failed
                job.error_message = f"Failed to publish to queue: {e}"
                db.commit()
                logger.error("Failed to publish crawl job to queue", extra={
                    "event": "scheduler_crawl_failed",
                    "source_id": source.id,
                    "source_name": source.name,
                    "job_id": job.id,
                    "reason": str(e),
                })

        if scheduled:
            logger.info("Scheduler run complete", extra={
                "event": "scheduler_run_complete",
                "scheduled_count": scheduled,
            })

    finally:
        db.close()  # always release the connection back to the pool


def _cleanup_expired_evidence() -> None:
    """
    Delete evidence files and records that have exceeded their retention period.

    Each source has a "retention_days_evidence" setting (default: 90 days).
    After this many days, the scraped files (screenshots, HTML dumps, PDFs)
    are deleted from S3 storage and their Evidence rows are removed from Postgres.

    Documents and their Qdrant chunks are NOT deleted here — they have a separate
    retention period handled by _cleanup_expired_index().

    Implementation detail: the expiry query uses Postgres interval arithmetic
    rather than computing dates in Python, so the filtering happens database-side
    and no expired rows need to be loaded into memory.
    """
    db = SessionLocal()
    try:
        # Find all evidence records where (created_at + retention_days) has passed
        # The text() wrapper is needed because SQLAlchemy cannot multiply an integer
        # column by a timedelta — we use raw SQL interval syntax instead.
        expired = (
            db.query(Evidence)
            .join(IngestJob, Evidence.job_id == IngestJob.id)
            .join(Source, IngestJob.source_id == Source.id)
            .filter(
                Evidence.created_at + (
                    Source.retention_days_evidence * text("interval '1 day'")
                ) <= func.now()
            )
            .all()
        )

        if not expired:
            logger.debug("Evidence cleanup: no expired records found")
            return

        storage = StorageService()  # S3/MinIO client for file deletion
        deleted_files = 0
        deleted_records = 0

        for evidence in expired:
            # Delete the file from S3 — errors are logged but don't abort the loop
            try:
                storage.delete(settings.s3_bucket_evidence, evidence.storage_uri)
                deleted_files += 1
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code != "NoSuchKey":
                    # NoSuchKey is acceptable (file already manually deleted)
                    # — any other error is worth logging
                    logger.warning(
                        f"Failed to delete file '{evidence.storage_uri}' "
                        f"from MinIO: {e}"
                    )

            # Delete the Evidence row from Postgres
            db.delete(evidence)
            deleted_records += 1

        db.commit()
        logger.info(
            f"Evidence cleanup: deleted {deleted_records} records "
            f"and {deleted_files} files from MinIO"
        )

    except Exception as e:
        logger.exception(f"Error during expired evidence cleanup: {e}")
        db.rollback()  # roll back any partial deletes to avoid inconsistent state
    finally:
        db.close()


def _cleanup_expired_index() -> None:
    """
    Delete documents and chunks that have exceeded their index retention period.

    Each source has a "retention_days_index" setting (default: 365 days).
    After this many days, the Document row, all its Chunk rows, and the
    corresponding Qdrant vectors are deleted.

    Process per expired document:
    1. Find all chunks belonging to the document that have been embedded (is_embedded=True).
    2. Delete their Qdrant vectors (so they can't be returned by search).
    3. Delete the Chunk rows from Postgres.
    4. Delete the Document row from Postgres.
    """
    from services.embedding import EmbeddingService

    db = SessionLocal()
    try:
        expired_docs = (
            db.query(Document)
            .join(Source, Document.source_id == Source.id)
            .filter(
                Document.created_at + (
                    Source.retention_days_index * text("interval '1 day'")
                ) <= func.now()
            )
            .all()
        )

        if not expired_docs:
            logger.debug("Index cleanup: no expired documents found")
            return

        embedding_service = EmbeddingService()  # for deleting Qdrant vectors
        deleted_chunks = 0
        deleted_docs = 0

        for doc in expired_docs:
            # Get all chunks for this document
            chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
            # Collect IDs of chunks that were actually embedded into Qdrant
            embedded_ids = [c.id for c in chunks if c.is_embedded]
            if embedded_ids:
                try:
                    # Remove vectors from Qdrant before deleting Postgres rows
                    embedding_service.delete_chunks(embedded_ids)
                except Exception as e:
                    logger.warning("Failed to delete chunks from Qdrant for doc %s: %s", doc.id, e)
            # Delete all chunk rows for this document
            for chunk in chunks:
                db.delete(chunk)
                deleted_chunks += 1
            db.delete(doc)
            deleted_docs += 1

        db.commit()
        logger.info(
            "Index cleanup: deleted %d documents and %d chunks", deleted_docs, deleted_chunks
        )

    except Exception:
        logger.exception("Error during expired index cleanup")
        db.rollback()
    finally:
        db.close()


def _refresh_gauges() -> None:
    """
    Update Prometheus Gauge metrics to reflect current database state.

    Gauges represent values that can go up or down (unlike Counters which only
    increase). These three gauges give operators a quick view of system health
    on the Grafana dashboard without running SQL queries manually.

    - ACTIVE_SOURCES: How many sources the scheduler is monitoring.
    - OPEN_INCIDENTS: How many CAPTCHA/block events need curator attention.
    - QDRANT_COLLECTION_SIZE: Approximate number of indexed chunks (proxy for
      "how much content has been embedded into the vector database").
    """
    db = SessionLocal()
    try:
        ACTIVE_SOURCES.set(db.query(Source).filter(Source.is_active == True).count())
        OPEN_INCIDENTS.set(db.query(Incident).filter(Incident.status == IncidentStatus.open).count())
        # Count chunks with is_embedded=True as a proxy for Qdrant vector count
        # (avoids making a network call to Qdrant on every gauge refresh)
        QDRANT_COLLECTION_SIZE.set(db.query(Chunk).filter(Chunk.is_embedded == True).count())
    except Exception:
        logger.exception("Failed to refresh Prometheus gauges")
    finally:
        db.close()


def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance with all background tasks.

    The scheduler is an AsyncIOScheduler — it runs inside the FastAPI async
    event loop, so async jobs would work, but all our jobs are synchronous
    (they create their own DB sessions and do blocking I/O). APScheduler
    runs synchronous jobs in a thread pool so they don't block the event loop.

    The scheduler is started/stopped in main.py's lifespan handler:
    - start() is called on application startup
    - shutdown() is called on application shutdown

    Returns:
        A fully configured (but not yet started) AsyncIOScheduler.
    """
    scheduler = AsyncIOScheduler()

    # Task 1: Check for due sources every 5 minutes, start immediately on launch
    scheduler.add_job(
        _schedule_due_sources,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="crawl_scheduler",
        name="Automatic crawl scheduler",
        replace_existing=True,
        next_run_time=datetime.utcnow(),  # run immediately on startup
    )

    # Task 2: Delete expired evidence files (daily, offset by 1 hour from startup)
    scheduler.add_job(
        _cleanup_expired_evidence,
        trigger="interval",
        hours=CLEANUP_INTERVAL_HOURS,
        id="evidence_cleanup",
        name="Expired evidence cleanup",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(hours=1),
    )

    # Task 3: Delete expired documents and chunks (daily, offset by 2 hours)
    # Offset from Task 2 so both don't run simultaneously and compete for DB connections
    scheduler.add_job(
        _cleanup_expired_index,
        trigger="interval",
        hours=CLEANUP_INTERVAL_HOURS,
        id="index_cleanup",
        name="Expired index/document cleanup",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(hours=2),
    )

    # Task 4: Update Prometheus gauges every 5 minutes, start immediately
    scheduler.add_job(
        _refresh_gauges,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="gauge_refresh",
        name="Prometheus gauge refresh",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )

    # Tasks 5–8: Sync/heal jobs via SyncService
    # SyncService needs both an EmbeddingService (for Qdrant access) and a
    # queue service adapter (to publish re-embedding jobs to RabbitMQ).
    from services.embedding import EmbeddingService
    from services.queue import publish_embedding_job as queue_embed_fn

    class QueueServiceAdapter:
        """Adapts the queue module's publish_embedding_job() function to the
        interface expected by SyncService.publish_embedding_job(doc_id, priority)."""
        def publish_embedding_job(self, doc_id: str, priority: str = 'normal'):
            queue_embed_fn(doc_id, priority)

    sync_service = SyncService(
        embedding_service=EmbeddingService(),
        queue_service=QueueServiceAdapter()
    )

    # Task 5: Detect chunks stuck in "pending" for > 10 minutes and requeue them
    # (Guards against worker crashes that leave chunks without a consumer)
    scheduler.add_job(
        lambda: sync_service.heal_pending_embeddings(SessionLocal()),
        trigger="interval",
        minutes=5,
        id="heal_pending_embeddings",
        name="Heal pending embeddings",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(minutes=5),
    )

    # Task 6: Retry chunks that failed embedding (up to 3 attempts)
    scheduler.add_job(
        lambda: sync_service.heal_failed_embeddings(SessionLocal()),
        trigger="interval",
        minutes=settings.heal_interval_minutes,
        id="heal_failed_embeddings",
        name="Retry failed embeddings",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(minutes=10),
    )

    # Task 7: Compare Postgres and Qdrant counts; alert if they diverge too much
    scheduler.add_job(
        lambda: sync_service.detect_qdrant_drift(SessionLocal()),
        trigger="interval",
        minutes=settings.heal_interval_minutes,
        id="detect_qdrant_drift",
        name="Detect Qdrant drift",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(minutes=15),
    )

    # Task 8: Re-sync chunks that are "done" in Postgres but missing from Qdrant
    scheduler.add_job(
        lambda: sync_service.heal_qdrant_sync(SessionLocal(), max_chunks=100),
        trigger="interval",
        minutes=30,
        id="heal_qdrant_sync",
        name="Heal Qdrant sync",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(minutes=20),
    )

    return scheduler
