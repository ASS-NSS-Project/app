"""
services/sync.py - Consistency healing between Postgres and Qdrant

Postgres and Qdrant can drift out of sync when:
- The embedding worker crashes mid-batch (chunks stuck in "pending")
- The embedding step fails permanently after 3 retries (status "failed")
- A Qdrant node is temporarily unreachable (chunks marked "done" in Postgres
  but the Qdrant upsert never completed — qdrant_sync_status stays "missing")
- The Postgres DB/PVC is restored from a backup but Qdrant is not
  (Qdrant has vectors from before the restore — orphaned points)

This service runs as scheduled background jobs (registered in scheduler.py).
It does NOT run continuously — it fires every 5–30 minutes and
corrects whatever drift it finds.

Note: drift detection and healing are best-effort. A large undetected drift
(e.g. Qdrant was wiped and rebuilt from an older snapshot) would require a
manual full re-embedding triggered by an admin.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SyncService:
    """
    Detects and repairs inconsistencies between Postgres chunk records and
    Qdrant vector points.

    Injected dependencies:
    - embedding_service: Used to access the Qdrant client (for count queries and
      delete operations).
    - queue_service: Used to publish re-embedding jobs to RabbitMQ when chunks
      need to be re-embedded.
    """

    def __init__(self, embedding_service, queue_service):
        """
        Args:
            embedding_service: An EmbeddingService instance (provides Qdrant access).
            queue_service: An object with a publish_embedding_job(doc_id, priority) method.
        """
        self.embedding_service = embedding_service
        self.queue_service = queue_service

    def heal_pending_embeddings(self, db: Session) -> int:
        """
        Find chunks stuck in "pending" for more than 10 minutes and requeue them.

        A chunk stays "pending" when:
        - The embedding worker received the RabbitMQ message but crashed before
          it could update the status (the message was re-queued by RabbitMQ after
          the worker's heartbeat expired, but Postgres still shows "pending").
        - The RabbitMQ message was published but never consumed (worker was down).

        The 10-minute threshold is generous — a normal embedding job for a full
        document takes less than 30 seconds. Anything older than 10 minutes is
        almost certainly stuck.

        Re-queuing sends a fresh RabbitMQ message with priority "high" (logged
        as a healing job, not a normal ingest-triggered embedding).

        Args:
            db: Active database session.

        Returns:
            Number of documents for which a re-embedding job was published.
        """
        from models import Chunk

        # Cutoff: 10 minutes ago — anything older is considered stuck
        cutoff = datetime.utcnow() - timedelta(minutes=10)

        # Find document IDs that have at least one stuck chunk
        # (DISTINCT so we publish one job per document, not one per chunk)
        stuck_doc_ids = (
            db.query(Chunk.document_id)
            .filter(
                Chunk.embedding_status == 'pending',
                Chunk.created_at < cutoff  # chunk was created more than 10 min ago
            )
            .distinct()
            .all()
        )

        requeued = 0
        for (doc_id,) in stuck_doc_ids:
            # Publish a high-priority re-embedding job for this document
            self.queue_service.publish_embedding_job(doc_id, priority='high')
            requeued += 1
            logger.info(
                "Requeued embedding job for stuck document",
                extra={"event": "heal_pending_requeued", "document_id": doc_id}
            )

        if requeued > 0:
            logger.warning(
                f"Healed {requeued} stuck pending embeddings",
                extra={"event": "heal_pending_complete", "requeued": requeued}
            )

        return requeued

    def heal_failed_embeddings(self, db: Session) -> int:
        """
        Retry chunks that failed embedding, up to a maximum of 3 attempts.

        A chunk enters "failed" status when the embedding worker catches an
        exception (e.g. BGE-M3 OOM crash, Qdrant unavailable) during the
        embedding batch.

        Retry strategy:
        - Reset the failed chunks to "pending" so the worker will re-try them.
        - Publish a new embedding job to RabbitMQ.
        - Only retry if retry_count < 3 — after 3 failures, the chunk stays
          "failed" so an admin can investigate rather than spinning forever.

        Args:
            db: Active database session.

        Returns:
            Number of documents for which a retry job was published.
        """
        from models import Chunk

        # Find documents that have failed chunks with fewer than 3 attempts
        failed_doc_ids = (
            db.query(Chunk.document_id)
            .filter(
                Chunk.embedding_status == 'failed',
                Chunk.retry_count < 3  # give up after 3 failures
            )
            .distinct()
            .all()
        )

        requeued = 0
        for (doc_id,) in failed_doc_ids:
            # Reset status so the worker will pick them up again
            db.query(Chunk).filter(
                Chunk.document_id == doc_id,
                Chunk.embedding_status == 'failed'
            ).update({'embedding_status': 'pending'})
            db.commit()

            self.queue_service.publish_embedding_job(doc_id, priority='normal')
            requeued += 1
            logger.info(
                "Retrying failed embedding",
                extra={"event": "heal_failed_retry", "document_id": doc_id}
            )

        if requeued > 0:
            logger.warning(
                f"Retrying {requeued} failed embeddings",
                extra={"event": "heal_failed_complete", "requeued": requeued}
            )

        return requeued

    def detect_qdrant_drift(self, db: Session) -> dict:
        """
        Compare the number of embedded chunks in Postgres with the number of
        points in Qdrant and alert if they differ by more than the threshold.

        Why counts might differ:
        - Qdrant was reset but Postgres was not (Qdrant count < Postgres count)
        - Postgres was restored from a backup but Qdrant was not
          (orphaned vectors: Qdrant count > Postgres count)
        - Transient embedding failures caused some chunks to be skipped

        The drift threshold is set by settings.drift_alert_threshold_pct (e.g. 10%).
        If drift exceeds the threshold AND settings.auto_resync_on_drift is True,
        this method also triggers heal_qdrant_sync() to start fixing it.

        Args:
            db: Active database session.

        Returns:
            Dict with "postgres_count", "qdrant_count", and "drift_pct" keys.
            Includes "error" key if the Qdrant count query failed.
        """
        from models import Chunk

        # Count chunks that are fully embedded according to Postgres
        pg_count = (
            db.query(func.count(Chunk.id))
            .filter(Chunk.embedding_status == 'done')
            .scalar() or 0
        )

        # Count all points currently stored in the Qdrant collection
        try:
            qdrant_count = self.embedding_service.qdrant.count(
                collection_name=settings.qdrant_collection
            ).count
        except Exception as e:
            logger.error(
                f"Failed to count Qdrant points: {e}",
                extra={"event": "qdrant_count_failed", "error": str(e)}
            )
            return {
                "postgres_count": pg_count,
                "qdrant_count": 0,
                "drift_pct": 100.0,
                "error": str(e)
            }

        # Calculate percentage difference between the two counts
        if pg_count == 0:
            # Both empty = no drift; Qdrant non-empty with empty Postgres = full drift
            drift_pct = 0.0 if qdrant_count == 0 else 100.0
        else:
            drift_pct = abs(pg_count - qdrant_count) / pg_count * 100

        result = {
            "postgres_count": pg_count,
            "qdrant_count": qdrant_count,
            "drift_pct": drift_pct
        }

        if drift_pct > settings.drift_alert_threshold_pct:
            logger.warning(
                f"Qdrant drift detected: {drift_pct:.1f}% difference",
                extra={"event": "qdrant_drift_detected", **result}
            )

            if settings.auto_resync_on_drift:
                # Automatically begin resyncing the out-of-sync chunks
                logger.info(
                    "Auto-triggering Qdrant resync due to drift",
                    extra={"event": "auto_resync_triggered"}
                )
                self.heal_qdrant_sync(db, max_chunks=1000)
        else:
            logger.debug(
                f"Qdrant drift check: {drift_pct:.1f}% difference (OK)",
                extra={"event": "qdrant_drift_check", **result}
            )

        return result

    def heal_qdrant_sync(self, db: Session, max_chunks: int = 100) -> int:
        """
        Re-embed chunks that are "done" in Postgres but not synced to Qdrant.

        A chunk can be in this state when:
        - The EmbeddingService.embed_chunks() completed the Postgres update but
          the Qdrant upsert timed out.
        - The Qdrant node was temporarily unavailable during the batch upsert.

        The qdrant_sync_status field tracks this: "synced" means the vector is in
        Qdrant; anything else (e.g. "missing", "pending") means it needs re-syncing.

        We process chunks in batches grouped by document_id, then publish one
        low-priority RabbitMQ job per document to re-embed that document's chunks.

        Args:
            db: Active database session.
            max_chunks: Maximum chunks to process in one scheduler run
                        (limits the blast radius if many chunks are out of sync).

        Returns:
            Total number of chunks for which re-embedding was triggered.
        """
        from models import Chunk
        from collections import defaultdict

        # Find chunks that are "done" in Postgres but flagged as not synced to Qdrant
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
            return 0  # nothing to do

        # Group by document_id so we publish one job per document
        by_doc: dict[str, list] = defaultdict(list)
        for chunk in out_of_sync:
            by_doc[chunk.document_id].append(chunk)

        resynced = 0
        for doc_id, chunks in by_doc.items():
            # Low priority: healing jobs are less urgent than new ingest-triggered ones
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
            extra={"event": "heal_qdrant_sync_complete", "resynced": resynced}
        )

        return resynced
