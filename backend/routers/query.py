"""
routers/query.py - RAG Query Endpoint
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import User
from routers.auth import get_authenticated_user
from services.rag_service import RAGService
from services.auth_service import log_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])


class QueryRequest(BaseModel):
    question: str
    mode: str = "rag"                    # "rag" or "no_rag"
    top_k: int = 5                       # How many chunks to retrieve
    source_id: Optional[str] = None      # Restrict to one source
    strict_grounding: bool = True        # Only answer from retrieved context
    # Optional custom upstream LLM — any OpenAI-compatible endpoint
    upstream_base_url: Optional[str] = None
    upstream_api_key: Optional[str] = None
    upstream_model: Optional[str] = None


class CitationResponse(BaseModel):
    index: int
    url: str
    text: str
    relevance_score: float


class QueryResponse(BaseModel):
    answer: str
    mode: str
    citations: list[CitationResponse]
    chunks_retrieved: int


@router.post("/", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    Ask a question. Returns an answer with citations.
    
    Modes:
    - rag: Retrieve relevant chunks first, then answer (recommended)
    - no_rag: Ask model directly (for comparison/benchmarking)
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    logger.info("Query received", extra={
        "event": "query_received",
        "mode": request.mode,
        "top_k": request.top_k,
        "source_id": request.source_id,
        "strict_grounding": request.strict_grounding,
        "question": request.question[:200],
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
        )
    except RuntimeError as e:
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
    log_action(
        db, current_user.id, "QUERY_EXECUTED",
        extra={
            "question": request.question[:200],
            "mode": request.mode,
            "chunks_retrieved": result["chunks_retrieved"],
        }
    )
    return result
