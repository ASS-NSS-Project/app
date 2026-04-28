"""
services/scheduler_service.py - Automatic crawl scheduling, cleanup, and sync

Periodic tasks:

1. _schedule_due_sources (every CHECK_INTERVAL_MINUTES minutes)
   Checks which sources are "due" and schedules their crawl.
   A source is due when last_crawled_at IS NULL or
   last_crawled_at + crawl_frequency_hours <= now().

2. _cleanup_expired_evidence (once every CLEANUP_INTERVAL_HOURS hours)
   Deletes evidence records (DB + files in MinIO) whose retention period
   defined on the source (retention_days_evidence) has elapsed.

3. _cleanup_expired_index (once every CLEANUP_INTERVAL_HOURS hours, offset 2 h)
   Deletes documents and chunks past their index retention period.

4. _refresh_gauges (every CHECK_INTERVAL_MINUTES minutes)
   Updates Prometheus gauges that reflect current DB state.
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
from services.queue import publish_job
from services.storage import StorageService

logger = logging.getLogger(__name__)
settings = get_settings()

# How often the scheduler checks whether sources are due
CHECK_INTERVAL_MINUTES = 5

# How often expired evidence cleanup runs (in hours)
CLEANUP_INTERVAL_HOURS = 24


def _schedule_due_sources() -> None:
    """
    Checks all active sources and for those that are due,
    creates an IngestJob record in the DB and publishes it to RabbitMQ.

    Synchronous function – APScheduler runs it in a thread pool
    so it doesn't block the async event loop.
    """
    db = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.is_active == True).all()
        now = datetime.utcnow()
        scheduled = 0

        for source in sources:
            # Calculate whether the source is due
            if source.last_crawled_at is None:
                due = True
            else:
                due = now >= source.last_crawled_at + timedelta(hours=source.crawl_frequency_hours)

            if not due:
                continue

            # Create the job record in the DB
            job = IngestJob(
                source_id=source.id,
                url=source.base_url,
                status=JobStatus.pending,
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            # Publish to RabbitMQ – the worker will pick it up and process it
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
        db.close()


def _cleanup_expired_evidence() -> None:
    """
    Deletes evidence records whose retention period has elapsed.

    Each source has retention_days_evidence configured (default: 90 days).
    After this period the following are deleted:
      - files from MinIO (screenshots, HTML dumps, …)
      - records from the evidence table in the DB

    Documents and Qdrant chunks are kept – they have their own
    retention period (retention_days_index) and will be handled separately.
    """
    db = SessionLocal()
    try:
        # Find expired evidence using PostgreSQL interval arithmetic:
        # evidence.created_at + (source.retention_days_evidence days) <= now
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

        storage = StorageService()
        deleted_files = 0
        deleted_records = 0

        for evidence in expired:
            # Delete the file from MinIO
            try:
                storage.delete(settings.s3_bucket_evidence, evidence.storage_uri)
                deleted_files += 1
            except ClientError as e:
                # File may have been deleted manually – log but don't abort
                error_code = e.response["Error"]["Code"]
                if error_code != "NoSuchKey":
                    logger.warning(
                        f"Failed to delete file '{evidence.storage_uri}' "
                        f"from MinIO: {e}"
                    )

            # Delete the DB record
            db.delete(evidence)
            deleted_records += 1

        db.commit()
        logger.info(
            f"Evidence cleanup: deleted {deleted_records} records "
            f"and {deleted_files} files from MinIO"
        )

    except Exception as e:
        logger.exception(f"Error during expired evidence cleanup: {e}")
        db.rollback()
    finally:
        db.close()


def _cleanup_expired_index() -> None:
    """
    Deletes documents and chunks whose index retention period has elapsed.

    Each source has retention_days_index configured (default: 365 days).
    Chunks are deleted from PostgreSQL; Qdrant vectors are removed by chunk ID.
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

        embedding_service = EmbeddingService()
        deleted_chunks = 0
        deleted_docs = 0

        for doc in expired_docs:
            chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
            embedded_ids = [c.id for c in chunks if c.is_embedded]
            if embedded_ids:
                try:
                    embedding_service.delete_chunks(embedded_ids)
                except Exception as e:
                    logger.warning("Failed to delete chunks from Qdrant for doc %s: %s", doc.id, e)
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
    """Update Prometheus gauges that reflect current DB/Qdrant state."""
    db = SessionLocal()
    try:
        ACTIVE_SOURCES.set(db.query(Source).filter(Source.is_active == True).count())
        OPEN_INCIDENTS.set(db.query(Incident).filter(Incident.status == IncidentStatus.open).count())
        QDRANT_COLLECTION_SIZE.set(db.query(Chunk).filter(Chunk.is_embedded == True).count())
    except Exception:
        logger.exception("Failed to refresh Prometheus gauges")
    finally:
        db.close()


def create_scheduler() -> AsyncIOScheduler:
    """
    Creates and configures an APScheduler instance.

    The scheduler is registered in the application lifespan (main.py)
    and starts/stops together with the API process.
    """
    scheduler = AsyncIOScheduler()

    # Task 1: crawl scheduling
    scheduler.add_job(
        _schedule_due_sources,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="crawl_scheduler",
        name="Automatic crawl scheduler",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )

    # Task 2: expired evidence cleanup
    # Runs once a day – not immediately on startup, but after 1 hour
    scheduler.add_job(
        _cleanup_expired_evidence,
        trigger="interval",
        hours=CLEANUP_INTERVAL_HOURS,
        id="evidence_cleanup",
        name="Expired evidence cleanup",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(hours=1),
    )

    # Task 3: expired index/document cleanup
    scheduler.add_job(
        _cleanup_expired_index,
        trigger="interval",
        hours=CLEANUP_INTERVAL_HOURS,
        id="index_cleanup",
        name="Expired index/document cleanup",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(hours=2),
    )

    # Task 4: refresh Prometheus gauges every 5 minutes
    scheduler.add_job(
        _refresh_gauges,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="gauge_refresh",
        name="Prometheus gauge refresh",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )

    return scheduler
