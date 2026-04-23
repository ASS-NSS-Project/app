"""
services/rag_service.py - RAG Query Engine

RAG = Retrieval-Augmented Generation

Without RAG: Ask the LLM a question → answers from its training data
With RAG:    Ask the LLM a question →
             1. Find relevant text chunks from OUR database
             2. Give those chunks to the LLM as context
             3. LLM answers based on OUR data, with citations

Uses the e-INFRA AIaaS OpenAI-compatible API (AIAAS_BASE_URL / AIAAS_LLM_MODEL).
"""

import logging
import re
import time
from typing import Optional

import httpx
from openai import AsyncOpenAI, APITimeoutError, APIStatusError
from sqlalchemy.orm import Session

from config import get_settings
from services.embedding_service import EmbeddingService
from services.metrics import QUERY_REQUESTS_TOTAL, QUERY_DURATION

logger = logging.getLogger(__name__)
settings = get_settings()

# Module-level singletons — created once, reused across requests
_embedder: Optional[EmbeddingService] = None
_llm_client: Optional[AsyncOpenAI] = None


def _get_embedder() -> EmbeddingService:
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService()
    return _embedder


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            base_url=settings.aiaas_base_url,
            api_key=settings.aiaas_api_key,
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0),
        )
    return _llm_client


class RAGService:
    """
    Handles both RAG and no-RAG query modes.
    """

    def __init__(self):
        self.client = _get_llm_client()
        self.embedder = _get_embedder()

    async def query(
        self,
        question: str,
        mode: str = "rag",
        top_k: int = 5,
        source_id: Optional[str] = None,
        strict_grounding: bool = True,
        db: Optional[Session] = None,
    ) -> dict:
        t0 = time.monotonic()
        if mode == "rag":
            result = await self._query_rag(question, top_k, source_id, strict_grounding, db)
        else:
            result = await self._query_no_rag(question)
        QUERY_REQUESTS_TOTAL.labels(mode=mode).inc()
        QUERY_DURATION.labels(mode=mode).observe(time.monotonic() - t0)
        return result

    async def _query_rag(
        self,
        question: str,
        top_k: int,
        source_id: Optional[str],
        strict_grounding: bool,
        db: Optional[Session] = None,
    ) -> dict:
        # Step 1: Retrieve relevant chunks (text fetched from Postgres via db)
        chunks = self.embedder.search(query=question, top_k=top_k, source_id=source_id, db=db)

        if not chunks:
            return {
                "answer": "I could not find any relevant information in the knowledge base for this question.",
                "mode": "rag",
                "citations": [],
                "chunks_retrieved": 0,
            }

        # Step 2: Build context string from retrieved chunks
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(f"[{i}] Source: {chunk['citation_url']}\n{chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)

        # Step 3: Call LLM
        logger.info("Sending RAG query to LLM (%s): '%s'", settings.aiaas_llm_model, question[:80])
        try:
            response = await self.client.chat.completions.create(
                model=settings.aiaas_llm_model,
                max_tokens=2048,
                extra_body={"enable_thinking": False},
                messages=[
                    {"role": "system", "content": self._build_rag_system_prompt(strict_grounding)},
                    {"role": "user", "content": (
                        f"Context documents:\n\n{context}\n\n---\n\n"
                        f"Question: {question}\n\n"
                        f"Answer based on the context documents above. "
                        f"Cite sources using [1], [2], etc. notation. "
                        f"If the context doesn't contain enough information to answer, say so clearly."
                    )},
                ],
            )
        except APITimeoutError:
            logger.error("LLM request timed out", extra={
                "event": "llm_timeout",
                "model": settings.aiaas_llm_model,
                "mode": "rag",
            })
            raise RuntimeError(
                f"LLM request timed out after 180 s. "
                f"Check that AIAAS_BASE_URL and AIAAS_LLM_MODEL are correct ({settings.aiaas_llm_model})."
            )
        except APIStatusError as e:
            logger.error("LLM API error", extra={
                "event": "llm_error",
                "model": settings.aiaas_llm_model,
                "mode": "rag",
                "status_code": e.status_code,
                "detail": e.message,
            })
            raise RuntimeError(f"LLM API returned {e.status_code}: {e.message}")

        answer = self._strip_thinking(response.choices[0].message.content or "")

        citations = [
            {
                "index": i + 1,
                "url": chunk["citation_url"],
                "text": chunk["text"][:300] + "..." if len(chunk["text"]) > 300 else chunk["text"],
                "relevance_score": round(chunk["score"], 3),
            }
            for i, chunk in enumerate(chunks)
        ]

        return {
            "answer": answer,
            "mode": "rag",
            "citations": citations,
            "chunks_retrieved": len(chunks),
        }

    async def _query_no_rag(self, question: str) -> dict:
        """No-RAG mode: ask the LLM directly, no retrieval."""
        logger.info("Sending no-RAG query to LLM (%s)", settings.aiaas_llm_model)
        try:
            response = await self.client.chat.completions.create(
                model=settings.aiaas_llm_model,
                max_tokens=2048,
                extra_body={"enable_thinking": False},
                messages=[{"role": "user", "content": question}],
            )
        except APITimeoutError:
            logger.error("LLM request timed out", extra={
                "event": "llm_timeout",
                "model": settings.aiaas_llm_model,
                "mode": "no_rag",
            })
            raise RuntimeError(
                f"LLM request timed out after 180 s. "
                f"Check that AIAAS_BASE_URL and AIAAS_LLM_MODEL are correct ({settings.aiaas_llm_model})."
            )
        except APIStatusError as e:
            logger.error("LLM API error", extra={
                "event": "llm_error",
                "model": settings.aiaas_llm_model,
                "mode": "no_rag",
                "status_code": e.status_code,
                "detail": e.message,
            })
            raise RuntimeError(f"LLM API returned {e.status_code}: {e.message}")

        return {
            "answer": self._strip_thinking(response.choices[0].message.content or ""),
            "mode": "no_rag",
            "citations": [],
            "chunks_retrieved": 0,
        }

    @staticmethod
    def _strip_thinking(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _build_rag_system_prompt(self, strict_grounding: bool) -> str:
        if strict_grounding:
            return """You are a precise research assistant with access to a curated knowledge base.

RULES:
1. Answer ONLY using the information in the provided context documents
2. Every factual claim must be supported by a citation [1], [2], etc.
3. If the context doesn't contain the answer, explicitly say: "The available documents do not contain information about this."
4. Do NOT use your general knowledge to fill gaps
5. Be concise and factual

Your citations allow users to verify every claim you make."""
        else:
            return """You are a helpful research assistant.
You have been provided with context documents from a knowledge base.
Use these documents as your primary source, but you may supplement with general knowledge when clearly needed.
Always cite the context documents when you use them with [1], [2], etc. notation."""
