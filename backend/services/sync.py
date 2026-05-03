"""
services/sync.py - Sync & Heal Background Service

Detects and automatically fixes drift between Postgres and Qdrant.
Runs as scheduled jobs via APScheduler.

Jobs:
- heal_pending_embeddings: Requeue chunks stuck in 'pending' for >10 minutes
- heal_failed_embeddings: Retry failed embeddings (if retry_count < 3)
- detect_qdrant_drift: Compare Postgres and Qdrant counts, alert if >10% difference
- heal_qdrant_sync: Re-sync chunks marked as done but not in Qdrant
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SyncService:
    """Background service to maintain consistency between Postgres and Qdrant"""

    def __init__(self, embedding_service, queue_service):
        """
        Args:
            embedding_service: EmbeddingService instance (for Qdrant access)
            queue_service: QueueService instance (for publishing jobs)
        """
        self.embedding_service = embedding_service
        self.queue_service = queue_service

    def heal_pending_embeddings(self, db: Session) -> int:
        """
        Find chunks stuck in 'pending' for >10 minutes and requeue.

        Returns:
            Number of documents requeued
        """
        from models import Chunk

        cutoff = datetime.utcnow() - timedelta(minutes=10)

        # Find documents with stuck chunks
        stuck_doc_ids = (
            db.query(Chunk.document_id)
            .filter(
                Chunk.embedding_status == 'pending',
                Chunk.created_at < cutoff
            )
            .distinct()
            .all()
        )

        requeued = 0
        for (doc_id,) in stuck_doc_ids:
            self.queue_service.publish_embedding_job(doc_id, priority='high')
            requeued += 1
            logger.info(
                "Requeued embedding job for stuck document",
                extra={
                    "event": "heal_pending_requeued",
                    "document_id": doc_id
                }
            )

        if requeued > 0:
            logger.warning(
                f"Healed {requeued} stuck pending embeddings",
                extra={
                    "event": "heal_pending_complete",
                    "requeued": requeued
                }
            )

        return requeued

    def heal_failed_embeddings(self, db: Session) -> int:
        """
        Retry failed embeddings (if retry_count < 3).

        Returns:
            Number of documents requeued
        """
        from models import Chunk

        failed_doc_ids = (
            db.query(Chunk.document_id)
            .filter(
                Chunk.embedding_status == 'failed',
                Chunk.retry_count < 3
            )
            .distinct()
            .all()
        )

        requeued = 0
        for (doc_id,) in failed_doc_ids:
            # Reset status to pending
            db.query(Chunk).filter(
                Chunk.document_id == doc_id,
                Chunk.embedding_status == 'failed'
            ).update({'embedding_status': 'pending'})
            db.commit()

            self.queue_service.publish_embedding_job(doc_id, priority='normal')
            requeued += 1
            logger.info(
                "Retrying failed embedding",
                extra={
                    "event": "heal_failed_retry",
                    "document_id": doc_id
                }
            )

        if requeued > 0:
            logger.warning(
                f"Retrying {requeued} failed embeddings",
                extra={
                    "event": "heal_failed_complete",
                    "requeued": requeued
                }
            )

        return requeued

    def detect_qdrant_drift(self, db: Session) -> dict:
        """
        Compare Postgres and Qdrant counts.

        Returns:
            Dict with {"postgres_count", "qdrant_count", "drift_pct"}
        """
        from models import Chunk

        # Count chunks marked as done in Postgres
        pg_count = (
            db.query(func.count(Chunk.id))
            .filter(Chunk.embedding_status == 'done')
            .scalar() or 0
        )

        # Count points in Qdrant
        try:
            qdrant_count = self.embedding_service.qdrant.count(
                collection_name=settings.qdrant_collection
            ).count
        except Exception as e:
            logger.error(
                f"Failed to count Qdrant points: {e}",
                extra={
                    "event": "qdrant_count_failed",
                    "error": str(e)
                }
            )
            return {
                "postgres_count": pg_count,
                "qdrant_count": 0,
                "drift_pct": 100.0,
                "error": str(e)
            }

        # Calculate drift percentage
        if pg_count == 0:
            drift_pct = 0.0 if qdrant_count == 0 else 100.0
        else:
            drift_pct = abs(pg_count - qdrant_count) / pg_count * 100

        result = {
            "postgres_count": pg_count,
            "qdrant_count": qdrant_count,
            "drift_pct": drift_pct
        }

        # Alert if drift exceeds threshold
        if drift_pct > settings.drift_alert_threshold_pct:
            logger.warning(
                f"Qdrant drift detected: {drift_pct:.1f}% difference",
                extra={
                    "event": "qdrant_drift_detected",
                    **result
                }
            )

            # Auto-trigger resync if enabled
            if settings.auto_resync_on_drift:
                logger.info(
                    "Auto-triggering Qdrant resync due to drift",
                    extra={"event": "auto_resync_triggered"}
                )
                self.heal_qdrant_sync(db, max_chunks=1000)
        else:
            logger.debug(
                f"Qdrant drift check: {drift_pct:.1f}% difference (OK)",
                extra={
                    "event": "qdrant_drift_check",
                    **result
                }
            )

        return result

    def heal_qdrant_sync(self, db: Session, max_chunks: int = 100) -> int:
        """
        Find chunks marked as done but not synced to Qdrant, and re-sync.

        Args:
            max_chunks: Maximum number of chunks to re-sync in one run

        Returns:
            Number of chunks re-synced
        """
        from models import Chunk
        from collections import defaultdict

        # Find out-of-sync chunks
        out_of_sync = (
            db.query(Chunk)
            .filter(
                Chunk.embedding_status == 'done',
                Chunk.qdrant_sync_status != 'synced'
            )
            .limit(max_chunks)
            .all()
        )

        if not out_of_sync:
            return 0

        # Group by document for batch processing
        by_doc = defaultdict(list)
        for chunk in out_of_sync:
            by_doc[chunk.document_id].append(chunk)

        resynced = 0
        for doc_id, chunks in by_doc.items():
            # Requeue embedding job with low priority
            self.queue_service.publish_embedding_job(doc_id, priority='low')
            resynced += len(chunks)
            logger.info(
                f"Requeued {len(chunks)} out-of-sync chunks for re-embedding",
                extra={
                    "event": "heal_qdrant_sync_requeue",
                    "document_id": doc_id,
                    "chunk_count": len(chunks)
                }
            )

        logger.warning(
            f"Healed {resynced} out-of-sync chunks",
            extra={
                "event": "heal_qdrant_sync_complete",
                "resynced": resynced
            }
        )

        return resynced
