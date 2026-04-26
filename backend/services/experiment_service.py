import logging
import math
import re
import time
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from config import get_settings
from models import Experiment, ExperimentQuery, ExperimentStatus
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def _generate_answer(question: str, retrieved_texts: list[str]) -> str | None:
    """Synchronous LLM call to produce a RAG answer for experiment evaluation."""
    settings = get_settings()
    if not settings.aiaas_base_url or not settings.aiaas_api_key:
        return None
    context = "\n\n---\n\n".join(retrieved_texts[:5])
    messages = [
        {"role": "system", "content": "Answer based only on the provided context. Be concise."},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
    ]
    try:
        resp = httpx.post(
            f"{settings.aiaas_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.aiaas_api_key}"},
            json={"model": settings.aiaas_llm_model, "messages": messages, "max_tokens": 512},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    except Exception as exc:
        logger.warning("LLM answer generation skipped in experiment: %s", exc)
        return None


def _recall_at_k(retrieved: list[str], keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    hits = sum(
        1 for kw in keywords
        if any(kw.lower() in chunk_text.lower() for chunk_text in retrieved)
    )
    return hits / len(keywords)


def _mrr(retrieved: list[str], keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    for rank, text in enumerate(retrieved, start=1):
        if any(kw.lower() in text.lower() for kw in keywords):
            return 1.0 / rank
    return 0.0


def _ndcg(retrieved: list[str], keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    relevances = [
        1.0 if any(kw.lower() in text.lower() for kw in keywords) else 0.0
        for text in retrieved
    ]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))
    ideal = sorted(relevances, reverse=True)
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


class ExperimentService:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()

    def run(self, experiment_id: str) -> Experiment:
        experiment = self.db.query(Experiment).filter(Experiment.id == experiment_id).first()
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        logger.info("Experiment started", extra={
            "event": "experiment_started",
            "experiment_id": experiment_id,
            "experiment_name": experiment.name,
        })
        experiment.status = ExperimentStatus.running
        self.db.commit()

        try:
            self._execute(experiment)
            experiment.status = ExperimentStatus.done
            logger.info("Experiment completed", extra={
                "event": "experiment_completed",
                "experiment_id": experiment_id,
                "recall_at_k": experiment.recall_at_k,
                "mrr": experiment.mrr,
                "ndcg": experiment.ndcg,
                "avg_latency_ms": experiment.avg_latency_ms,
            })
        except Exception as e:
            logger.exception("Experiment %s failed", experiment_id, extra={
                "event": "experiment_failed",
                "experiment_id": experiment_id,
                "error": str(e),
            })
            experiment.status = ExperimentStatus.failed
            experiment.error_message = str(e)
        finally:
            experiment.finished_at = datetime.utcnow()
            self.db.commit()

        return experiment

    def _execute(self, experiment: Experiment) -> None:
        queries = (
            self.db.query(ExperimentQuery)
            .filter(ExperimentQuery.experiment_id == experiment.id)
            .all()
        )
        if not queries:
            raise ValueError("Experiment has no queries")

        logger.info("Experiment executing %d queries", len(queries), extra={
            "event": "experiment_executing",
            "experiment_id": experiment.id,
            "query_count": len(queries),
            "top_k": experiment.top_k,
        })
        recall_scores, mrr_scores, ndcg_scores, latencies = [], [], [], []

        for i, eq in enumerate(queries, 1):
            t0 = time.monotonic()
            hits = self.embedding_service.search(
                query=eq.query_text,
                top_k=experiment.top_k,
                db=self.db,
            )
            latency_ms = (time.monotonic() - t0) * 1000

            retrieved_texts = [h["text"] for h in hits]
            retrieved_ids = [h["chunk_id"] for h in hits]

            r = _recall_at_k(retrieved_texts, eq.expected_keywords)
            m = _mrr(retrieved_texts, eq.expected_keywords)
            n = _ndcg(retrieved_texts, eq.expected_keywords)

            eq.recall_at_k = r
            eq.mrr = m
            eq.ndcg = n
            eq.latency_ms = latency_ms
            eq.retrieved_chunk_ids = retrieved_ids
            eq.generated_answer = _generate_answer(eq.query_text, retrieved_texts)

            recall_scores.append(r)
            mrr_scores.append(m)
            ndcg_scores.append(n)
            latencies.append(latency_ms)

            logger.debug("Experiment query %d/%d done", i, len(queries), extra={
                "event": "experiment_query_done",
                "experiment_id": experiment.id,
                "query_index": i,
                "total": len(queries),
                "recall_at_k": round(r, 3),
                "latency_ms": round(latency_ms),
            })

        self.db.commit()

        experiment.recall_at_k = sum(recall_scores) / len(recall_scores)
        experiment.mrr = sum(mrr_scores) / len(mrr_scores)
        experiment.ndcg = sum(ndcg_scores) / len(ndcg_scores)
        experiment.avg_latency_ms = sum(latencies) / len(latencies)
