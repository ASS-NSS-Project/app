import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserRole, Document, Chunk, Evidence
from routers.auth import get_authenticated_user, require_role
from services.storage import StorageService
from services.embedding import EmbeddingService
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


class MarkdownUrlResponse(BaseModel):
    document_id: str
    url: str
    expires_in: int = 3600


class DocumentStatsResponse(BaseModel):
    documents: int
    chunks: int
    embedded_pct: int
    sources: int


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


@router.get("/stats", response_model=DocumentStatsResponse)
def get_document_stats(
    source_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    doc_q = db.query(Document)
    if source_id:
        doc_q = doc_q.filter(Document.source_id == source_id)

    documents = doc_q.count()
    sources = doc_q.with_entities(Document.source_id).distinct().count()

    chunk_q = db.query(Chunk)
    if source_id:
        chunk_q = chunk_q.join(Document, Chunk.document_id == Document.id).filter(Document.source_id == source_id)

    chunks = chunk_q.count()
    embedded = chunk_q.filter(Chunk.is_embedded == True).count()
    embedded_pct = round((embedded / chunks) * 100) if chunks else 0

    return DocumentStatsResponse(
        documents=documents,
        chunks=chunks,
        embedded_pct=embedded_pct,
        sources=sources,
    )


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


@router.get("/{doc_id}/markdown-url", response_model=MarkdownUrlResponse)
def get_markdown_url(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.markdown_uri:
        raise HTTPException(status_code=404, detail="No markdown file stored for this document")
    parts = doc.markdown_uri[5:].split("/", 1)
    bucket, key = parts[0], parts[1]
    storage = StorageService()
    try:
        presigned = storage.get_presigned_url(bucket=bucket, key=key, expires_seconds=3600)
    except Exception as e:
        logger.error("Failed to generate presigned URL for document %s: %s", doc_id, e,
                     extra={"event": "presigned_url_failed", "document_id": doc_id, "error": str(e)},
                     exc_info=True)
        raise HTTPException(status_code=500, detail="Could not generate document URL")
    return MarkdownUrlResponse(document_id=doc_id, url=presigned)


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """Delete a document and all of its chunks (including embedded vectors in Qdrant)."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = db.query(Chunk).filter(Chunk.document_id == doc_id).all()
    embedded_ids = [c.id for c in chunks if c.is_embedded]

    if embedded_ids:
        try:
            EmbeddingService().delete_chunks(embedded_ids)
        except Exception as e:
            logger.warning(
                "Failed to delete vectors from Qdrant for document %s: %s",
                doc_id,
                e,
                extra={"event": "chunks_delete_failed", "document_id": doc_id, "error": str(e)},
            )

    for chunk in chunks:
        db.delete(chunk)
    db.delete(doc)
    db.commit()
