"""
routers/query.py - RAG Query Endpoint
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import User
from routers.auth import get_authenticated_user
from services.rag_service import RAGService
from services.auth_service import log_action

router = APIRouter(prefix="/query", tags=["Query"])


class QueryRequest(BaseModel):
    question: str
    mode: str = "rag"                    # "rag" or "no_rag"
    top_k: int = 5                       # How many chunks to retrieve
    source_id: Optional[str] = None      # Restrict to one source
    strict_grounding: bool = True        # Only answer from retrieved context


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
    - no_rag: Ask Claude directly (for comparison/benchmarking)
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    rag_service = RAGService()
    result = await rag_service.query(
        question=request.question,
        mode=request.mode,
        top_k=request.top_k,
        source_id=request.source_id,
        strict_grounding=request.strict_grounding,
        db=db,
    )

    log_action(
        db, current_user.id, "QUERY_EXECUTED",
        extra={
            "question": request.question[:200],
            "mode": request.mode,
            "chunks_retrieved": result["chunks_retrieved"],
        },
    )

    return result
