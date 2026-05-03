"""
services/rag_service.py - RAG Query Engine

RAG = Retrieval-Augmented Generation

Without RAG: Ask the LLM a question → answers from its training data
With RAG:    Ask the LLM a question →
             1. Find relevant text chunks from OUR database
             2. Give those chunks to the LLM as context
             3. LLM answers based on OUR data, with citations

Uses any OpenAI-compatible API endpoint (QUERY_BASE_URL / QUERY_MODEL).
"""

import logging
import re
import time
from typing import Optional

import httpx
from openai import AsyncOpenAI, APITimeoutError, APIStatusError
from sqlalchemy.orm import Session

from config import get_settings
from services.embedding import EmbeddingService
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
            base_url=settings.query_base_url,
            api_key=settings.query_api_key,
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
        upstream_base_url: Optional[str] = None,
        upstream_api_key: Optional[str] = None,
        upstream_model: Optional[str] = None,
    ) -> dict:
        t0 = time.monotonic()

        # Custom upstream client (user-provided API key + base URL)
        if upstream_base_url and not upstream_api_key:
            raise RuntimeError(
                f"An API key is required for external provider ({upstream_base_url}). "
                "Enter your key in the API KEY field."
            )

        if upstream_base_url and upstream_api_key:
            client = AsyncOpenAI(
                base_url=upstream_base_url,
                api_key=upstream_api_key,
                timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0),
            )
            model = upstream_model or settings.query_model
            # enable_thinking is an AIaaS-specific extension (suppresses chain-of-thought
            # output from DeepSeek/Qwen3 reasoning models). Standard OpenAI/Anthropic APIs
            # reject unknown extra_body fields, so we must not send it to external providers.
            aiaas_extras = False
            logger.info("Using upstream provider %s model=%s", upstream_base_url, model,
                        extra={"event": "upstream_provider", "base_url": upstream_base_url, "model": model})
        else:
            client = self.client
            model = upstream_model or settings.query_model
            aiaas_extras = True

        if mode == "rag":
            result = await self._query_rag(question, top_k, source_id, strict_grounding, db, client, model, aiaas_extras)
        else:
            result = await self._query_no_rag(question, client, model, aiaas_extras)
        QUERY_REQUESTS_TOTAL.labels(mode=mode).inc()
        QUERY_DURATION.labels(mode=mode).observe(time.monotonic() - t0)
        return result

    def _check_qdrant_health(self) -> bool:
        """Ping Qdrant to check if it's responsive"""
        try:
            self.embedder.qdrant.get_collection(settings.qdrant_collection)
            return True
        except Exception as e:
            logger.warning(
                "Qdrant health check failed",
                extra={
                    "event": "qdrant_health_check_failed",
                    "error": str(e)
                }
            )
            return False

    def _keyword_search(
        self,
        db: Session,
        query: str,
        top_k: int,
        source_id: Optional[str] = None
    ) -> list[dict]:
        """
        Fallback to Postgres full-text search using tsvector.

        Args:
            db: Database session
            query: Search query
            top_k: Number of results to return
            source_id: Optional source filter

        Returns:
            List of chunk dicts with same format as vector search
        """
        from models import Chunk, Document
        from sqlalchemy import func, text

        logger.info(
            "Using keyword fallback search",
            extra={
                "event": "keyword_search_start",
                "query": query[:100],
                "top_k": top_k
            }
        )

        # Convert query to tsquery format
        tsquery = func.plainto_tsquery('english', query)

        # Build base query
        q = db.query(Chunk).filter(
            func.ts_match(Chunk.text_vector, tsquery)
        )

        # Optional source filter
        if source_id:
            q = q.join(Document).filter(Document.source_id == source_id)

        # Order by relevance rank and limit
        q = q.order_by(
            func.ts_rank(Chunk.text_vector, tsquery).desc()
        ).limit(top_k * 2)  # Fetch extra for diversity

        try:
            results = q.all()
        except Exception as e:
            logger.error(
                f"Keyword search failed: {e}",
                extra={
                    "event": "keyword_search_failed",
                    "error": str(e)
                }
            )
            return []

        # Format results to match vector search output
        formatted = []
        for chunk in results[:top_k]:
            formatted.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "citation_url": chunk.citation_url,
                "score": 0.5  # Fixed score for keyword matches
            })

        logger.info(
            f"Keyword search returned {len(formatted)} chunks",
            extra={
                "event": "keyword_search_complete",
                "chunk_count": len(formatted)
            }
        )

        return formatted

    async def _query_rag(
        self,
        question: str,
        top_k: int,
        source_id: Optional[str],
        strict_grounding: bool,
        db: Optional[Session] = None,
        client: Optional[AsyncOpenAI] = None,
        model: Optional[str] = None,
        aiaas_extras: bool = True,
    ) -> dict:
        # Step 1: Retrieve relevant chunks
        chunks = []
        search_mode = "rag"
        warning = None

        # Try vector search first (if Qdrant is healthy)
        if self._check_qdrant_health():
            try:
                chunks = self.embedder.search(
                    query=question,
                    top_k=top_k,
                    source_id=source_id,
                    db=db
                )
            except Exception as e:
                logger.warning(
                    f"Vector search failed: {e}",
                    extra={
                        "event": "vector_search_failed",
                        "error": str(e)
                    }
                )
                chunks = []

        # Fallback to keyword search if no results or Qdrant down
        if not chunks and settings.enable_keyword_fallback and db:
            logger.info("Falling back to keyword search")
            chunks = self._keyword_search(db, question, top_k, source_id)
            search_mode = "keyword_fallback"
            warning = "Vector search unavailable, using keyword fallback"

        # If still no chunks, return "no information" response
        if not chunks:
            if strict_grounding:
                return {
                    "answer": "I cannot answer this from the currently retrieved sources.",
                    "mode": search_mode,
                    "citations": [],
                    "chunks_retrieved": 0,
                    "warning": "Strict grounding is enabled and no sufficient grounded context was found.",
                    "grounding_mode": "strict",
                    "grounded_claim_ratio": 1.0,
                    "verification_passed": True,
                }
            return {
                "answer": "I could not find any relevant information in the knowledge base for this question.",
                "mode": search_mode,
                "citations": [],
                "chunks_retrieved": 0,
                "warning": "No sources available",
                "grounding_mode": "relaxed",
                "grounded_claim_ratio": 0.0,
                "verification_passed": None,
            }

        # Step 2: Build context string from retrieved chunks
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(f"[{i}] Source: {chunk['citation_url']}\n{chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)

        # Step 3: Call LLM
        client = client or self.client
        model = model or settings.query_model
        logger.info("Sending RAG query to LLM (%s): '%s'", model, question[:80])
        extra_kwargs = {"extra_body": {"enable_thinking": False}} if aiaas_extras else {}
        try:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=2048,
                temperature=0.0 if strict_grounding else 0.3,
                **extra_kwargs,
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
                "model": model,
                "mode": "rag",
            })
            raise RuntimeError(
                f"LLM request timed out after 180 s. "
                f"Check that the API base URL and model name are correct ({model})."
            )
        except APIStatusError as e:
            logger.error("LLM API error", extra={
                "event": "llm_error",
                "model": model,
                "mode": "rag",
                "status_code": e.status_code,
                "detail": e.message,
            })
            raise RuntimeError(f"LLM API returned {e.status_code}: {e.message}")

        answer = self._strip_thinking(response.choices[0].message.content or "")
        verification = self._verify_grounding(answer, chunks) if strict_grounding else None

        citations = [
            {
                "index": i + 1,
                "url": chunk["citation_url"],
                "text": chunk["text"][:300] + "..." if len(chunk["text"]) > 300 else chunk["text"],
                "relevance_score": round(chunk["score"], 3),
            }
            for i, chunk in enumerate(chunks)
        ]

        if strict_grounding and verification and not verification["passed"]:
            return {
                "answer": "I cannot provide a strictly grounded answer from the retrieved context.",
                "mode": search_mode,
                "citations": citations,
                "chunks_retrieved": len(chunks),
                "warning": "Strict grounding verification failed: unsupported claims detected.",
                "grounding_mode": "strict",
                "grounded_claim_ratio": verification["ratio"],
                "verification_passed": False,
            }

        relaxed_warning = warning
        if not strict_grounding and not relaxed_warning:
            relaxed_warning = "Relaxed grounding mode: answer may include model knowledge beyond retrieved sources."

        return {
            "answer": answer,
            "mode": search_mode,
            "citations": citations,
            "chunks_retrieved": len(chunks),
            "warning": relaxed_warning if not strict_grounding else warning,
            "grounding_mode": "strict" if strict_grounding else "relaxed",
            "grounded_claim_ratio": verification["ratio"] if verification else None,
            "verification_passed": verification["passed"] if verification else None,
        }

    async def _query_no_rag(
        self,
        question: str,
        client: Optional[AsyncOpenAI] = None,
        model: Optional[str] = None,
        aiaas_extras: bool = True,
    ) -> dict:
        """No-RAG mode: ask the LLM directly, no retrieval."""
        client = client or self.client
        model = model or settings.query_model
        logger.info("Sending no-RAG query to LLM (%s)", model)
        extra_kwargs = {"extra_body": {"enable_thinking": False}} if aiaas_extras else {}
        try:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=2048,
                **extra_kwargs,
                messages=[{"role": "user", "content": question}],
            )
        except APITimeoutError:
            logger.error("LLM request timed out", extra={
                "event": "llm_timeout",
                "model": model,
                "mode": "no_rag",
            })
            raise RuntimeError(
                f"LLM request timed out after 180 s. "
                f"Check that the API base URL and model name are correct ({model})."
            )
        except APIStatusError as e:
            logger.error("LLM API error", extra={
                "event": "llm_error",
                "model": model,
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
            "grounding_mode": "relaxed",
            "grounded_claim_ratio": 0.0,
            "verification_passed": None,
            "warning": "No RAG mode: response is not grounded in indexed sources.",
        }

    @staticmethod
    def _strip_thinking(text: str) -> str:
        # DeepSeek-R1 and Qwen3 emit chain-of-thought inside <think>…</think> before
        # the answer. Strip it so users see only the final response, not the reasoning trace.
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

    def _verify_grounding(self, answer: str, chunks: list[dict]) -> dict:
        """
        Lightweight strict-grounding verifier.
        Checks whether answer claim-like sentences include citations and whether
        citation IDs are valid for retrieved chunks.
        """
        if not answer.strip():
            return {"passed": False, "ratio": 0.0}

        max_idx = len(chunks)
        # Split by sentence terminators and newlines; robust enough for multilingual text.
        claims = [c.strip() for c in re.split(r"[.!?\n]+", answer) if c.strip()]
        if not claims:
            return {"passed": False, "ratio": 0.0}

        supported = 0
        for claim in claims:
            refs = re.findall(r"\[(\d+)\]", claim)
            if not refs:
                continue
            valid_refs = [int(r) for r in refs if 1 <= int(r) <= max_idx]
            if valid_refs:
                supported += 1

        ratio = supported / len(claims)
        return {"passed": ratio >= 0.8, "ratio": round(ratio, 3)}
