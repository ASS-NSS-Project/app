"""
routers/query.py - RAG Query Endpoint

Exposes the question-answering API to the frontend and external callers.

Endpoints:
  GET  /query/models — list the configured LLM models (for the model selector)
  POST /query/       — ask a question; returns an answer with source citations

The POST endpoint supports two modes:
  rag     — embed the question → search Qdrant → build context → ask LLM
  no_rag  — skip retrieval, ask the LLM directly (for comparison/benchmarking)

Custom LLM providers (OpenAI, OpenRouter) are supported when the user supplies
their own upstream_provider, upstream_api_key, and upstream_model fields.
Only these two external providers are allowed (SSRF guard in RAGService).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from config import get_settings
from database import get_db
from models import User
from routers.auth import get_authenticated_user
from services.rag import RAGService
from services.auth import log_action


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])


# --- Pydantic Schemas ---

class QueryRequest(BaseModel):
    """
    Request body for POST /query/.

    Fields:
        question: The user's natural-language question.
        mode: "rag" (default, retrieval-augmented) or "no_rag" (direct LLM).
        top_k: How many chunks to retrieve from Qdrant as context (default 5).
        source_id: Optional UUID — if set, only search chunks from this source.
        strict_grounding: If True, LLM is instructed to only use retrieved
                          context and cite every claim. If False, the LLM may
                          supplement with general knowledge.
        upstream_*: Optional custom LLM provider settings (OpenAI or OpenRouter).
                    Leave empty to use the server's configured QUERY_BASE_URL/QUERY_MODEL.
    """
    question: str
    mode: str = "rag"
    top_k: int = 5
    source_id: Optional[str] = None
    strict_grounding: bool = True
    # Custom provider fields — all optional, all must be set together
    upstream_provider: Optional[str] = None   # "openai" or "openrouter"
    upstream_base_url: Optional[str] = None   # API base URL (optional override)
    upstream_api_key: Optional[str] = None    # API key for the external provider
    upstream_model: Optional[str] = None      # model name (e.g. "gpt-4o")


class ModelInfo(BaseModel):
    """One entry in the model selector dropdown."""
    id: str      # internal identifier
    label: str   # display name shown in the UI
    model: str   # API model name string
    group: str   # grouping label (e.g. "Default", "OpenAI")


class CitationResponse(BaseModel):
    """One source citation attached to an answer."""
    index: int           # citation number used in the answer text ([1], [2], etc.)
    url: str             # source URL to link to
    text: str            # truncated chunk text preview
    relevance_score: float


class QueryResponse(BaseModel):
    """Full response for POST /query/."""
    answer: str
    mode: str
    citations: list[CitationResponse]
    chunks_retrieved: int
    model_name: Optional[str] = None
    warning: Optional[str] = None          # e.g. "keyword fallback used"
    grounding_mode: str = "strict"
    grounded_claim_ratio: Optional[float] = None  # 0.0–1.0; fraction of claims with citations
    verification_passed: Optional[bool] = None


# --- Routes ---

@router.get("/models", response_model=list[ModelInfo])
def get_models(current_user: User = Depends(get_authenticated_user)):
    """
    Return the list of available LLM models for the query UI model selector.

    Currently returns only the default server-configured model.
    Custom OpenAI/OpenRouter models are entered manually in the UI
    and not listed here.
    """
    settings = get_settings()
    return [
        {
            "id": "default",
            "label": settings.query_model or "default",
            "model": settings.query_model or "",
            "group": "Default"
        }
    ]


@router.post("/", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    Ask a question against the indexed knowledge base.

    The endpoint delegates to RAGService.query() which:
    1. (RAG mode) Embeds the question with BGE-M3 and searches Qdrant.
    2. Passes the retrieved chunks as context to the LLM.
    3. Returns the answer with numbered citations pointing to source URLs.

    HTTP 502 is returned for LLM-side errors (timeout, API auth failure, etc.)
    so the frontend can show a meaningful error toast rather than a generic 500.

    The query is logged to the audit_logs table so admins can review what
    questions were asked and what answers were returned.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # No-RAG mode doesn't support grounding checks (no sources to cite)
    if request.mode == "no_rag":
        request.strict_grounding = False

    logger.info("Query received", extra={
        "event": "query_received",
        "mode": request.mode,
        "top_k": request.top_k,
        "source_id": request.source_id,
        "strict_grounding": request.strict_grounding,
        "question": request.question[:200],  # truncate PII-sensitive content in logs
        "user_id": current_user.id,
    })

    rag_service = RAGService()
    try:
        result = await rag_service.query(
            question=request.question,
            mode=request.mode,
            top_k=request.top_k,
            source_id=request.source_id,
            strict_grounding=request.strict_grounding,
            db=db,
            upstream_base_url=request.upstream_base_url,
            upstream_api_key=request.upstream_api_key,
            upstream_model=request.upstream_model,
            upstream_provider=request.upstream_provider,
        )
    except RuntimeError as e:
        # RuntimeError from RAGService means the LLM call failed (timeout, bad API key, etc.)
        # Return 502 "Bad Gateway" — the downstream service (the LLM) failed, not us.
        logger.error("Query failed", extra={
            "event": "query_failed",
            "mode": request.mode,
            "question": request.question[:200],
            "error": str(e),
        }, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

    logger.info("Query completed", extra={
        "event": "query_completed",
        "mode": result["mode"],
        "chunks_retrieved": result["chunks_retrieved"],
    })

    # Write an immutable audit log entry so admins can review usage
    log_action(
        db, current_user.id, "QUERY_EXECUTED",
        extra={
            "question": request.question[:200],
            "mode": request.mode,
            "chunks_retrieved": result["chunks_retrieved"],
        }
    )
    return result
