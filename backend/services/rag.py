"""
services/rag.py - RAG Query Engine

RAG = Retrieval-Augmented Generation.

Without RAG: you ask the LLM a question and it answers from its training data —
             whatever it memorised months or years ago.
With RAG:    you ask the LLM a question and we:
             1. Embed the question as a vector and search OUR Qdrant knowledge base
             2. Hand the top-k matching text chunks to the LLM as "context documents"
             3. The LLM answers using OUR data and cites the sources with [1], [2], etc.

This module also supports "no-RAG" mode, where we skip retrieval and ask the LLM
directly (useful for general questions that don't require indexed content).

Custom providers (OpenAI, OpenRouter) are supported for power users who bring
their own API keys. Only these two are allowed — hardcoded host validation prevents
SSRF attacks where an attacker tries to route requests to internal services.
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

# These are module-level singletons: created once when first needed, then reused
# across all requests. Loading BGE-M3 takes ~10 s; we don't want that per request.
_embedder: Optional[EmbeddingService] = None
_llm_client: Optional[AsyncOpenAI] = None


def _get_embedder() -> EmbeddingService:
    """Return the shared EmbeddingService, loading BGE-M3 on first call."""
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService()
    return _embedder


def _get_llm_client() -> AsyncOpenAI:
    """Return the shared OpenAI-compatible client pointed at our default LLM endpoint."""
    global _llm_client
    if _llm_client is None:
        # Separate timeouts per operation: 10 s to open a TCP connection,
        # 180 s to read the full LLM stream (long responses can take a minute).
        _llm_client = AsyncOpenAI(
            base_url=settings.query_base_url,
            api_key=settings.query_api_key,
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0),
        )
    return _llm_client


def _is_openrouter_url(base_url: str) -> bool:
    """Return True if the base URL points to OpenRouter (needs special request headers)."""
    return "openrouter.ai" in base_url.lower()


def _openrouter_headers() -> dict[str, str]:
    """
    Build the extra HTTP headers OpenRouter requires.

    OpenRouter uses these for attribution and rate-limit grouping:
    - X-Title: human-readable app name shown in OpenRouter's dashboard
    - HTTP-Referer: the origin URL (optional but good practice)
    """
    headers = {"X-Title": "ASS-NSS WebRAG"}
    if settings.frontend_url:
        headers["HTTP-Referer"] = settings.frontend_url
    return headers


def _custom_provider_base_url(provider: Optional[str], base_url: Optional[str]) -> str:
    """
    Validate and return the base URL for a custom LLM provider.

    Security: we only allow OpenAI and OpenRouter. We check the hostname of
    the supplied URL against the expected host for the chosen provider.
    This prevents SSRF — an attacker cannot make the server call an internal
    service (e.g. http://postgres:5432/) by passing it as a provider URL.

    Args:
        provider: "openai" or "openrouter" (case-insensitive after strip).
        base_url: Optional override URL; defaults to the canonical API base.

    Returns:
        A validated base URL string.

    Raises:
        RuntimeError: If the provider is unsupported or the URL hostname doesn't match.
    """
    provider = (provider or "").strip()
    # Map of allowed providers: provider_key → (expected_hostname, default_base_url)
    allowed = {
        "openai": ("api.openai.com", "https://api.openai.com/v1"),
        "openrouter": ("openrouter.ai", "https://openrouter.ai/api/v1"),
    }
    if provider not in allowed:
        raise RuntimeError(
            "Unsupported custom provider. For security, this deployment only supports "
            "Default, OpenAI, and OpenRouter."
        )

    expected_host, default_base_url = allowed[provider]
    selected_base_url = (base_url or default_base_url).strip()
    try:
        # Parse the URL to extract just the hostname for validation
        host = httpx.URL(selected_base_url).host or ""
    except Exception as exc:
        raise RuntimeError(f"Invalid custom provider base URL: {selected_base_url}") from exc

    if host.lower() != expected_host:
        raise RuntimeError(
            f"Invalid base URL for {provider}. Expected host {expected_host}; got {host or 'empty'}."
        )
    return selected_base_url


class RAGService:
    """
    Handles the full RAG query lifecycle: retrieval + generation.

    Two modes:
    - "rag": embed the question → search Qdrant → build context → ask LLM → return answer + citations
    - "no_rag": skip retrieval, ask the LLM directly

    Supports both the default AIaaS endpoint and custom external providers
    (OpenAI, OpenRouter) when the user supplies their own API key.
    """

    def __init__(self):
        # Use the shared singleton LLM client (avoids re-opening TCP connections)
        self.client = _get_llm_client()
        # Lazy-loaded embedder — don't load BGE-M3 until the first search is needed
        self._embedder: Optional[EmbeddingService] = None

    @property
    def embedder(self) -> EmbeddingService:
        """Load (or return cached) EmbeddingService on first access."""
        if self._embedder is None:
            self._embedder = _get_embedder()
        return self._embedder

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
        upstream_provider: Optional[str] = None,
    ) -> dict:
        """
        Main entry point for a query request.

        Validates custom provider settings (if supplied), delegates to the
        appropriate internal method, records Prometheus metrics, and returns
        a result dict that the router serialises as JSON.

        Args:
            question: The natural-language question to answer.
            mode: "rag" (retrieval-augmented) or "no_rag" (direct LLM).
            top_k: How many chunks to retrieve from Qdrant for context.
            source_id: Optional UUID to restrict retrieval to one source's documents.
            strict_grounding: If True, LLM is instructed to cite every claim and
                              only use retrieved context (not general knowledge).
            db: Active SQLAlchemy session (needed for pre-flight DB checks in RAG mode).
            upstream_base_url: Custom provider API base URL (optional override).
            upstream_api_key: API key for the custom provider.
            upstream_model: Model name string (e.g. "gpt-4o").
            upstream_provider: "openai" or "openrouter" — required if any upstream_* given.

        Returns:
            Dict with keys: answer, mode, citations, chunks_retrieved, model_name,
            warning, grounding_mode, grounded_claim_ratio, verification_passed.
        """
        t0 = time.monotonic()

        # Validate: if the user passed any custom provider field, they must also set provider
        has_custom_provider = any([upstream_provider, upstream_base_url, upstream_api_key, upstream_model])
        if has_custom_provider and not upstream_provider:
            raise RuntimeError("Select OpenAI or OpenRouter when passing custom API values.")

        if has_custom_provider and not upstream_api_key:
            raise RuntimeError(
                "An API key is required for external providers. "
                "Enter your key in the API KEY field."
            )
        if has_custom_provider and not upstream_model:
            raise RuntimeError("A model name is required for external providers.")

        if has_custom_provider:
            # Build a fresh OpenAI-compatible client pointing at the external provider
            base_url = _custom_provider_base_url(upstream_provider, upstream_base_url)
            default_headers = _openrouter_headers() if _is_openrouter_url(base_url) else None
            client_kwargs = {
                "base_url": base_url,
                "api_key": upstream_api_key,
                "timeout": httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0),
            }
            if default_headers:
                client_kwargs["default_headers"] = default_headers
            client = AsyncOpenAI(**client_kwargs)
            model = upstream_model
            # enable_thinking is an AIaaS-specific extra_body field that suppresses
            # chain-of-thought output from DeepSeek/Qwen3 reasoning models.
            # Standard OpenAI and OpenRouter reject unknown extra_body fields,
            # so we must NOT send it when using a custom provider.
            aiaas_extras = False
            logger.info("Using upstream provider %s model=%s", base_url, model,
                        extra={"event": "upstream_provider", "base_url": base_url, "model": model})
        else:
            # Use the default shared client and configured model
            client = self.client
            model = upstream_model or settings.query_model
            # Our AIaaS supports enable_thinking to suppress reasoning traces
            aiaas_extras = True

        # Dispatch to RAG or no-RAG path
        if mode == "rag":
            result = await self._query_rag(question, top_k, source_id, strict_grounding, db, client, model, aiaas_extras)
        else:
            result = await self._query_no_rag(question, client, model, aiaas_extras)

        # Record Prometheus metrics for latency dashboards and alerting
        QUERY_REQUESTS_TOTAL.labels(mode=mode).inc()
        QUERY_DURATION.labels(mode=mode).observe(time.monotonic() - t0)
        return result

    def _check_qdrant_health(self) -> bool:
        """
        Lightweight ping to check whether Qdrant is reachable and the collection exists.

        Returns True if healthy; False if unreachable (triggers keyword fallback).
        """
        try:
            self.embedder.qdrant.get_collection(settings.qdrant_collection)
            return True
        except Exception as e:
            logger.warning(
                "Qdrant health check failed",
                extra={"event": "qdrant_health_check_failed", "error": str(e)}
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
        Fallback full-text search using Postgres tsvector when Qdrant is unavailable.

        Postgres has built-in full-text search via tsvector/tsquery. It is much less
        accurate than semantic vector search (it matches keywords, not meaning) but
        it works even when Qdrant is down.

        Args:
            db: Active database session.
            query: The search query string.
            top_k: Maximum number of chunks to return.
            source_id: Optional UUID to filter results to a single source.

        Returns:
            List of chunk dicts with keys: chunk_id, document_id, text,
            citation_url, score (always 0.5 — keyword matches have no relevance score).
        """
        from models import Chunk, Document
        from sqlalchemy import func

        logger.info(
            "Using keyword fallback search",
            extra={"event": "keyword_search_start", "query": query[:100], "top_k": top_k}
        )

        # plainto_tsquery converts free-form text like "university fees 2024"
        # into a Postgres tsquery (no need to quote or escape special chars)
        tsquery = func.plainto_tsquery('english', query)

        q = db.query(Chunk).filter(
            func.ts_match(Chunk.text_vector, tsquery)
        )

        if source_id:
            q = q.join(Document).filter(Document.source_id == source_id)

        # ts_rank() returns a float relevance score; order DESC puts best matches first
        q = q.order_by(
            func.ts_rank(Chunk.text_vector, tsquery).desc()
        ).limit(top_k * 2)  # fetch extra so we can trim after deduplication if needed

        try:
            results = q.all()
        except Exception as e:
            logger.error(
                f"Keyword search failed: {e}",
                extra={"event": "keyword_search_failed", "error": str(e)}
            )
            return []

        # Format results to match the structure returned by EmbeddingService.search()
        formatted = []
        for chunk in results[:top_k]:
            formatted.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "citation_url": chunk.citation_url,
                "score": 0.5,  # fixed sentinel — keyword matches have no cosine score
            })

        logger.info(
            f"Keyword search returned {len(formatted)} chunks",
            extra={"event": "keyword_search_complete", "chunk_count": len(formatted)}
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
        """
        Full RAG pipeline: pre-flight checks → retrieval → LLM generation → grounding check.

        Pre-flight checks: if the DB has no sources or no chunks yet, we skip retrieval
        and return a friendly "no content indexed yet" message in the user's language.

        Args:
            question: User's question.
            top_k: Number of chunks to pass as context.
            source_id: Optional filter to a single source's chunks.
            strict_grounding: If True, every claim must be cited and Qdrant-only sources used.
            db: DB session for pre-flight checks and chunk text lookups.
            client: OpenAI-compatible client (may be custom provider).
            model: Model name string.
            aiaas_extras: Whether to send AIaaS-specific extra_body fields.

        Returns:
            Result dict (see query() docstring for keys).
        """
        model = model or settings.query_model

        # Pre-flight: check whether there is any indexed content at all
        if db is not None:
            from models import Chunk, Document, Source

            if not source_id and db.query(Source).count() == 0:
                # No sources have been added to the system yet
                return await self._query_without_context(
                    question=question,
                    reason="No source has been inserted yet.",
                    mode="rag",
                    strict_grounding=strict_grounding,
                    client=client,
                    model=model,
                    aiaas_extras=aiaas_extras,
                )

            # Check whether the target source (or any source) has indexed chunks
            chunk_q = db.query(Chunk)
            if source_id:
                chunk_q = chunk_q.join(Document, Chunk.document_id == Document.id).filter(
                    Document.source_id == source_id
                )
            if chunk_q.count() == 0:
                message = (
                    "No content has been ingested for the selected source yet."
                    if source_id
                    else "No source content has been ingested yet."
                )
                return await self._query_without_context(
                    question=question,
                    reason=message,
                    mode="rag",
                    strict_grounding=strict_grounding,
                    client=client,
                    model=model,
                    aiaas_extras=aiaas_extras,
                )

        # --- Step 1: Retrieve relevant chunks from Qdrant (or keyword fallback)
        chunks = []
        search_mode = "rag"
        warning = None

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
                    extra={"event": "vector_search_failed", "error": str(e)}
                )
                chunks = []

        # Fall back to Postgres keyword search if Qdrant returned nothing or is down
        if not chunks and settings.enable_keyword_fallback and db:
            logger.info("Falling back to keyword search")
            chunks = self._keyword_search(db, question, top_k, source_id)
            search_mode = "keyword_fallback"
            warning = "Vector search unavailable, using keyword fallback"

        # If still no chunks, tell the user (in their own language)
        if not chunks:
            return await self._query_without_context(
                question=question,
                reason="No relevant documents were retrieved from the knowledge base.",
                mode=search_mode,
                strict_grounding=strict_grounding,
                client=client,
                model=model,
                aiaas_extras=aiaas_extras,
            )

        # --- Step 2: Format retrieved chunks as numbered context passages
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            # Each passage gets a number that the LLM uses as a citation reference
            context_parts.append(f"[{i}] Source: {chunk['citation_url']}\n{chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)

        # --- Step 3: Ask the LLM to answer using the context
        logger.info("Sending RAG query to LLM (%s): '%s'", model, question[:80])
        answer = await self._complete_chat(
            client=client,
            model=model,
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
            max_tokens=2048,
            temperature=0.0 if strict_grounding else 0.3,  # 0.0 = deterministic for strict mode
            aiaas_extras=aiaas_extras,
            mode="rag",
        )

        # Optional: verify that the answer cites retrieved chunks (strict mode)
        verification = self._verify_grounding(answer, chunks) if strict_grounding else None

        # Build citation objects for the API response
        citations = [
            {
                "index": i + 1,
                "url": chunk["citation_url"],
                # Truncate long chunks for the citation preview
                "text": chunk["text"][:300] + "..." if len(chunk["text"]) > 300 else chunk["text"],
                "relevance_score": round(chunk["score"], 3),
            }
            for i, chunk in enumerate(chunks)
        ]

        # If grounding verification failed, replace the answer with a refusal
        if strict_grounding and verification and not verification["passed"]:
            answer = await self._localized_strict_refusal(
                question=question,
                reason="Strict grounding verification failed because unsupported claims were detected.",
                client=client,
                model=model,
                aiaas_extras=aiaas_extras,
            )
            return {
                "answer": answer,
                "mode": search_mode,
                "citations": citations,
                "chunks_retrieved": len(chunks),
                "model_name": model,
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
            "model_name": model,
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
        """
        No-RAG mode: send the question directly to the LLM with no retrieved context.

        Used when the user wants a general answer not tied to indexed sources, or
        when comparing RAG vs. non-RAG quality in experiments.
        """
        model = model or settings.query_model
        logger.info("Sending no-RAG query to LLM (%s)", model)
        answer = await self._complete_chat(
            client=client,
            model=model,
            messages=[{"role": "user", "content": question}],
            max_tokens=2048,
            temperature=None,  # use model default temperature
            aiaas_extras=aiaas_extras,
            mode="no_rag",
        )

        return {
            "answer": answer,
            "mode": "no_rag",
            "citations": [],          # no sources to cite
            "chunks_retrieved": 0,
            "model_name": model,
            "grounding_mode": "relaxed",
            "grounded_claim_ratio": 0.0,
            "verification_passed": None,
            "warning": "No RAG mode: response is not grounded in indexed sources.",
        }

    async def _query_without_context(
        self,
        question: str,
        reason: str,
        mode: str,
        strict_grounding: bool,
        client: Optional[AsyncOpenAI],
        model: str,
        aiaas_extras: bool,
    ) -> dict:
        """
        Generate a user-facing "no content found" response when retrieval returns nothing.

        In strict mode: politely say we have no relevant indexed documents.
        In relaxed mode: say we have nothing indexed but still give a general answer.
        The LLM writes the message in the same language as the user's question.
        """
        if strict_grounding:
            answer = await self._localized_strict_refusal(
                question=question, reason=reason,
                client=client, model=model, aiaas_extras=aiaas_extras,
            )
        else:
            answer = await self._localized_relaxed_no_context_answer(
                question=question, reason=reason,
                client=client, model=model, aiaas_extras=aiaas_extras,
            )

        return {
            "answer": answer,
            "mode": mode,
            "citations": [],
            "chunks_retrieved": 0,
            "model_name": model,
            "warning": None,
            "grounding_mode": "strict" if strict_grounding else "relaxed",
            "grounded_claim_ratio": 1.0 if strict_grounding else 0.0,
            "verification_passed": True if strict_grounding else None,
        }

    async def _localized_strict_refusal(
        self,
        question: str,
        reason: str,
        client: Optional[AsyncOpenAI],
        model: str,
        aiaas_extras: bool,
    ) -> str:
        """
        Ask the LLM to produce a one-sentence refusal in the user's question language.

        We never hard-code "Sorry, I can't find that" in English — the user may be
        writing in Czech, German, etc. We instruct the LLM to match the language.
        """
        system = (
            "You write short user-facing RAG status messages. "
            "Answer in the same language as the user's question. "
            "Do not answer the user's topic. "
            "State that the indexed/retrieved documents do not contain enough information to answer."
        )
        user = (
            f"User question:\n{question}\n\n"
            f"Internal reason:\n{reason}\n\n"
            "Write one concise sentence for the user."
        )
        return await self._call_notice_llm(system, user, client, model, aiaas_extras)

    async def _localized_relaxed_no_context_answer(
        self,
        question: str,
        reason: str,
        client: Optional[AsyncOpenAI],
        model: str,
        aiaas_extras: bool,
    ) -> str:
        """
        In relaxed mode with no retrieved chunks, give a partial answer from general knowledge.

        Structure: first acknowledge that the knowledge base has nothing, then add
        1–3 sentences of general knowledge clearly labelled as "outside indexed sources".
        """
        system = (
            "You answer in the same language as the user's question. "
            "The knowledge base retrieval returned no usable documents. "
            "First state that no indexed/retrieved documents contain the answer. "
            "Then add a clearly separated general-knowledge answer introduced as outside the retrieved context. "
            "Keep the general-knowledge part to one to three sentences. Do not invent citations."
        )
        user = (
            f"User question:\n{question}\n\n"
            f"Internal reason:\n{reason}\n\n"
            "Write the final answer for relaxed RAG mode."
        )
        return await self._call_notice_llm(system, user, client, model, aiaas_extras)

    async def _call_notice_llm(
        self,
        system: str,
        user: str,
        client: Optional[AsyncOpenAI],
        model: str,
        aiaas_extras: bool,
    ) -> str:
        """Shared helper: send a short notice-style prompt and return the response text."""
        return await self._complete_chat(
            client=client,
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=300,   # short messages only — keep latency low
            temperature=0.0,  # deterministic output for notices
            aiaas_extras=aiaas_extras,
            mode="rag_notice",
        )

    async def _complete_chat(
        self,
        client: Optional[AsyncOpenAI],
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: Optional[float],
        aiaas_extras: bool,
        mode: str,
    ) -> str:
        """
        Low-level wrapper around OpenAI chat.completions.create().

        Handles the AIaaS-specific enable_thinking field, optional temperature,
        timeout errors, and API status errors — converting them all into RuntimeError
        with a human-readable message suitable for returning to the API caller.

        Args:
            client: The AsyncOpenAI client to use (default or custom).
            model: Model name string.
            messages: List of role/content dicts forming the chat history.
            max_tokens: Maximum tokens in the LLM response.
            temperature: Sampling temperature (0.0 = deterministic). None = use model default.
            aiaas_extras: If True, add enable_thinking=False to suppress reasoning traces.
            mode: Short label for logging (e.g. "rag", "no_rag", "rag_notice").

        Returns:
            The text content of the LLM's response, with thinking tags stripped.
        """
        try:
            client = client or self.client
            extra_kwargs = {}
            if aiaas_extras:
                # Suppress chain-of-thought output from DeepSeek/Qwen3 reasoning models.
                # Without this, the response starts with hundreds of tokens of internal reasoning
                # wrapped in <think>…</think> before the actual answer.
                extra_kwargs["extra_body"] = {"enable_thinking": False}
            if temperature is not None:
                extra_kwargs["temperature"] = temperature
            response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                **extra_kwargs,
                messages=messages,
            )
        except APITimeoutError:
            logger.error("LLM request timed out", extra={
                "event": "llm_timeout",
                "model": model,
                "mode": mode,
            })
            raise RuntimeError(
                f"LLM request timed out after 180 s. "
                f"Check that the API base URL and model name are correct ({model})."
            )
        except APIStatusError as e:
            logger.error("LLM API error", extra={
                "event": "llm_error",
                "model": model,
                "mode": mode,
                "status_code": e.status_code,
                "detail": e.message,
            })
            raise RuntimeError(f"LLM API returned {e.status_code}: {e.message}")
        except Exception as e:
            logger.error("LLM request failed", extra={
                "event": "llm_error",
                "model": model,
                "mode": mode,
                "detail": str(e),
            }, exc_info=True)
            raise RuntimeError(f"LLM request failed: {e}")

        return self._strip_thinking(response.choices[0].message.content or "")

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """
        Remove <think>…</think> blocks from the LLM output.

        DeepSeek-R1 and Qwen3 reasoning models emit their chain-of-thought inside
        <think> tags before the final answer. We strip these so users see only the
        conclusion, not the internal reasoning trace.
        The re.DOTALL flag makes '.' match newlines, needed for multi-line think blocks.
        """
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _build_rag_system_prompt(self, strict_grounding: bool) -> str:
        """
        Return the system prompt that tells the LLM how to behave.

        Strict mode: must cite every claim, must not use general knowledge.
        Relaxed mode: context preferred, general knowledge allowed as supplement.
        """
        if strict_grounding:
            return """You are a precise research assistant with access to a curated knowledge base.

RULES:
1. Answer ONLY using the information in the provided context documents
2. Every factual claim must be supported by a citation [1], [2], etc.
3. Answer in the same language as the user's question
4. If the context doesn't contain the answer, say so clearly in the user's language
5. Do NOT use your general knowledge to fill gaps
6. Be concise and factual

Your citations allow users to verify every claim you make."""
        else:
            return """You are a helpful research assistant.
You have been provided with context documents from a knowledge base.
Use these documents as your primary source, but you may supplement with general knowledge when clearly needed.
Answer in the same language as the user's question.
Always cite the context documents when you use them with [1], [2], etc. notation."""

    def _verify_grounding(self, answer: str, chunks: list[dict]) -> dict:
        """
        Check whether the LLM's answer adequately cites the retrieved chunks.

        Algorithm:
        1. Split the answer into individual sentences (claims).
        2. For each claim, look for citation references like [1], [2], [3].
        3. Check that each referenced index is within the range of retrieved chunks.
        4. Compute the ratio of supported claims to total claims.
        5. Pass if ≥80% of claims have valid citations.

        This is a lightweight heuristic — it does NOT check semantic accuracy,
        only that citation numbers are present and reference real retrieved chunks.

        Returns:
            Dict with "passed" (bool) and "ratio" (float 0.0–1.0).
        """
        if not answer.strip():
            return {"passed": False, "ratio": 0.0}

        max_idx = len(chunks)
        # Split on sentence-ending punctuation and newlines (handles multilingual text)
        claims = [c.strip() for c in re.split(r"[.!?\n]+", answer) if c.strip()]
        if not claims:
            return {"passed": False, "ratio": 0.0}

        supported = 0
        for claim in claims:
            # Find all [N] citation references in this sentence
            refs = re.findall(r"\[(\d+)\]", claim)
            if not refs:
                continue  # this claim has no citations at all
            # Check if at least one cited index is valid (1-based, within retrieved set)
            valid_refs = [int(r) for r in refs if 1 <= int(r) <= max_idx]
            if valid_refs:
                supported += 1

        ratio = supported / len(claims)
        # Require at least 80% of claims to have valid citations to "pass"
        return {"passed": ratio >= 0.8, "ratio": round(ratio, 3)}
