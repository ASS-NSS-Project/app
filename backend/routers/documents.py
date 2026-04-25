import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User, Document, Chunk, Evidence
from routers.auth import get_authenticated_user
from services.storage_service import StorageService
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/documents", tags=["Documents"])


class DocumentResponse(BaseModel):
    id: str
    source_id: str
    url: str
    title: Optional[str]
    doc_version: int
    quality_score: Optional[float]
    ingest_strategy: Optional[str]
    language: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_type: str
    text: str
    chunk_index: int
    citation_url: Optional[str]
    citation_evidence_id: Optional[str]
    section_path: Optional[str]
    token_count: Optional[int]
    is_embedded: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EvidenceUrlResponse(BaseModel):
    evidence_id: str
    url: str
    expires_in: int = 3600


@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    source_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    q = db.query(Document)
    if source_id:
        q = q.filter(Document.source_id == source_id)
    return q.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}/chunks", response_model=list[ChunkResponse])
def list_chunks(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.query(Chunk).filter(Chunk.document_id == doc_id).order_by(Chunk.chunk_index).all()


@router.get("/{doc_id}/markdown")
def get_document_markdown(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """Return the document's full Markdown content as a downloadable .md file."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.content_markdown:
        content = doc.content_markdown
    else:
        # Fallback: reconstruct from chunks for documents ingested before this feature
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == doc_id)
            .order_by(Chunk.chunk_index)
            .all()
        )
        content = "\n\n".join(c.text for c in chunks) if chunks else ""

    safe_title = (doc.title or doc.id)[:60].replace("/", "-").replace("\\", "-")
    filename = f"{safe_title}.md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/evidence/{evidence_id}/url", response_model=EvidenceUrlResponse)
def get_evidence_url(
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    storage = StorageService()
    try:
        presigned = storage.get_presigned_url(
            bucket=settings.s3_bucket_evidence,
            key=evidence.storage_uri,
            expires_seconds=3600,
        )
    except Exception as e:
        logger.error("Failed to generate presigned URL for evidence %s: %s", evidence_id, e,
                     extra={"event": "presigned_url_failed", "evidence_id": evidence_id, "error": str(e)},
                     exc_info=True)
        raise HTTPException(status_code=500, detail="Could not generate evidence URL")
    return EvidenceUrlResponse(evidence_id=evidence_id, url=presigned)
