"""
routers/query.py - RAG Query Endpoint
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


# ── Provider resolution ───────────────────────────────────────────────────────

_PROVIDER_BASE_URLS = {
    "openai":    "https://api.openai.com/v1",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/openai/",
    "anthropic": "https://api.anthropic.com/v1/",
}

_PROVIDER_MODELS = {
    "openai": [
        {"id": "openai:gpt-4.1",      "label": "GPT-4.1",       "model": "gpt-4.1"},
        {"id": "openai:gpt-4.1-mini", "label": "GPT-4.1 Mini",  "model": "gpt-4.1-mini"},
        {"id": "openai:gpt-4.1-nano", "label": "GPT-4.1 Nano",  "model": "gpt-4.1-nano"},
        {"id": "openai:gpt-4o",       "label": "GPT-4o",         "model": "gpt-4o"},
        {"id": "openai:gpt-4o-mini",  "label": "GPT-4o Mini",    "model": "gpt-4o-mini"},
        {"id": "openai:o4-mini",      "label": "o4-mini",        "model": "o4-mini"},
        {"id": "openai:o3",           "label": "o3",             "model": "o3"},
    ],
    "gemini": [
        {"id": "gemini:gemini-2.5-pro",   "label": "Gemini 2.5 Pro",   "model": "gemini-2.5-pro"},
        {"id": "gemini:gemini-2.5-flash", "label": "Gemini 2.5 Flash", "model": "gemini-2.5-flash"},
        {"id": "gemini:gemini-2.0-flash", "label": "Gemini 2.0 Flash", "model": "gemini-2.0-flash"},
        {"id": "gemini:gemini-3.0-flash", "label": "Gemini 3.0 Flash", "model": "gemini-3.0-flash"},
        {"id": "gemini:gemini-3.1-pro",   "label": "Gemini 3.1 Pro",   "model": "gemini-3.1-pro"},
    ],
    "anthropic": [
        {"id": "anthropic:claude-opus-4-7",        "label": "Claude Opus 4.7",   "model": "claude-opus-4-7"},
        {"id": "anthropic:claude-sonnet-4-6",      "label": "Claude Sonnet 4.6", "model": "claude-sonnet-4-6"},
        {"id": "anthropic:claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "model": "claude-haiku-4-5-20251001"},
    ],
}

_AIAAS_MODELS = [
    {"id": "aiaas:qwen3.5-122b",           "label": "Qwen3.5 122B · 256k",  "model": "qwen3.5-122b"},
    {"id": "aiaas:deepseek-v3.2-thinking", "label": "DeepSeek V3.2 · 160k", "model": "deepseek-v3.2-thinking"},
    {"id": "aiaas:gpt-oss-120b",           "label": "GPT-OSS 120B · 128k",  "model": "gpt-oss-120b"},
]


def _resolve_upstream(model_id: str, settings) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Given a preset model_id like 'openai:gpt-4o', return (base_url, api_key, model)."""
    if not model_id or ":" not in model_id:
        return None, None, model_id or None

    provider, model = model_id.split(":", 1)

    if provider == "aiaas":
        # Use the shared AIaaS endpoint, no custom URL/key needed
        return None, None, model

    base_url = _PROVIDER_BASE_URLS.get(provider)
    api_key = {
        "openai":    settings.openai_api_key,
        "gemini":    settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(provider, "")

    return base_url, api_key or None, model

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])


class QueryRequest(BaseModel):
    question: str
    mode: str = "rag"
    top_k: int = 5
    source_id: Optional[str] = None
    strict_grounding: bool = True
    # Preset model ID (e.g. "openai:gpt-4o") — backend resolves URL + key from config.
    # For custom endpoints, set upstream_base_url + upstream_api_key + upstream_model directly.
    model_id: Optional[str] = None
    upstream_base_url: Optional[str] = None
    upstream_api_key: Optional[str] = None
    upstream_model: Optional[str] = None


class ModelInfo(BaseModel):
    id: str
    label: str
    model: str
    group: str


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
    warning: Optional[str] = None


@router.get("/models", response_model=list[ModelInfo])
def get_models(current_user: User = Depends(get_authenticated_user)):
    settings = get_settings()
    models = [dict(group="AIaaS — e-INFRA", **m) for m in _AIAAS_MODELS]
    if settings.openai_api_key:
        models += [dict(group="OpenAI", **m) for m in _PROVIDER_MODELS["openai"]]
    if settings.gemini_api_key:
        models += [dict(group="Gemini", **m) for m in _PROVIDER_MODELS["gemini"]]
    if settings.anthropic_api_key:
        models += [dict(group="Claude", **m) for m in _PROVIDER_MODELS["anthropic"]]
    return models


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

    # Resolve preset model_id → base_url, api_key, model name
    if request.model_id:
        settings = get_settings()
        base_url, api_key, model = _resolve_upstream(request.model_id, settings)
    else:
        base_url  = request.upstream_base_url
        api_key   = request.upstream_api_key
        model     = request.upstream_model

    rag_service = RAGService()
    try:
        result = await rag_service.query(
            question=request.question,
            mode=request.mode,
            top_k=request.top_k,
            source_id=request.source_id,
            strict_grounding=request.strict_grounding,
            db=db,
            upstream_base_url=base_url,
            upstream_api_key=api_key,
            upstream_model=model,
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
