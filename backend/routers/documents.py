"""
routers/documents.py - Document and chunk browsing endpoints

Lets the frontend explore the knowledge base: list indexed documents,
browse their text chunks, download full Markdown content, and view
evidence screenshots via pre-signed S3 URLs.

Endpoints:
  GET  /documents/                        — list documents (filterable by source)
  GET  /documents/stats                   — aggregate counts for the KB dashboard
  GET  /documents/{id}                    — get one document's metadata
  GET  /documents/{id}/chunks             — list all chunks for a document
  GET  /documents/{id}/markdown           — download document as .md file
  GET  /documents/{id}/markdown-url       — get S3 pre-signed URL for the .md file
  GET  /documents/evidence/{id}/url       — get S3 pre-signed URL for a screenshot
  DELETE /documents/{id}                  — delete document + chunks + Qdrant vectors

Pre-signed URLs:
The API does NOT proxy evidence files (screenshots, HTML dumps) through itself.
Instead it generates a temporary pre-signed S3 URL valid for 1 hour and returns
it to the client. The browser then fetches directly from S3/MinIO, reducing API
server load and enabling large file downloads without streaming overhead.
"""
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


# --- Pydantic Schemas ---

class DocumentResponse(BaseModel):
    """Public representation of a Document row."""
    id: str
    source_id: str
    url: str
    title: Optional[str]
    doc_version: int         # incremented each time the page content changes
    quality_score: Optional[float]  # rough 0.0–1.0 content richness measure
    ingest_strategy: Optional[str]
    language: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    """Public representation of one text chunk."""
    id: str
    document_id: str
    chunk_type: str       # "text", "table", or "block"
    text: str
    chunk_index: int      # position within the document (0-based)
    citation_url: Optional[str]
    citation_evidence_id: Optional[str]
    section_path: Optional[str]  # heading breadcrumb (e.g. "Intro / Background")
    token_count: Optional[int]
    is_embedded: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EvidenceUrlResponse(BaseModel):
    """Response when requesting a pre-signed URL for an evidence file."""
    evidence_id: str
    url: str         # S3 pre-signed URL valid for expires_in seconds
    expires_in: int = 3600


class MarkdownUrlResponse(BaseModel):
    """Response when requesting a pre-signed URL for a document's .md file."""
    document_id: str
    url: str
    expires_in: int = 3600


class DocumentStatsResponse(BaseModel):
    """Aggregate statistics for the knowledge base dashboard."""
    documents: int
    chunks: int
    embedded_pct: int   # percentage of chunks that have been embedded into Qdrant
    sources: int


# --- Routes ---

@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    source_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """Return paginated documents, newest first, optionally filtered by source."""
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
    """
    Return aggregate document/chunk counts for the knowledge base dashboard.

    The embedded_pct shows what fraction of chunks have been vectorised into Qdrant.
    A value below 100% means some chunks are still pending embedding (normal if
    the embedding worker is busy) or failed embedding (check the logs).
    """
    doc_q = db.query(Document)
    if source_id:
        doc_q = doc_q.filter(Document.source_id == source_id)

    documents = doc_q.count()
    # Count distinct source_ids among the filtered documents
    sources = doc_q.with_entities(Document.source_id).distinct().count()

    chunk_q = db.query(Chunk)
    if source_id:
        chunk_q = chunk_q.join(Document, Chunk.document_id == Document.id).filter(
            Document.source_id == source_id
        )

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
    """Return one document's metadata by ID."""
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
    """Return all chunks for a document, ordered by their position in the document."""
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
    """
    Return the document's full Markdown content as a downloadable .md attachment.

    Primary: use Document.content_markdown (stored in Postgres for quick access).
    Fallback: if content_markdown is empty (older documents ingested before this
    field was added), reconstruct the text by concatenating chunk texts in order.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.content_markdown:
        content = doc.content_markdown
    else:
        # Older documents don't have content_markdown — reconstruct from chunks
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == doc_id)
            .order_by(Chunk.chunk_index)
            .all()
        )
        content = "\n\n".join(c.text for c in chunks) if chunks else ""

    # Build a safe filename from the document title (strip path separators)
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
    """
    Generate a temporary pre-signed S3 URL for an evidence file (e.g. a screenshot).

    The URL is valid for 1 hour. The client (browser) fetches the file directly
    from S3 using this URL — the API server does not proxy the file content.
    This keeps bandwidth and memory usage on the API server low.
    """
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
    """
    Generate a pre-signed S3 URL for the document's stored .md file.

    Only available if markdown_uri is set on the document (documents ingested
    after S3 backup was enabled). Older documents return 404.

    The markdown_uri is stored as "s3://bucket/path/key" — we strip the
    "s3://" prefix and split on the first "/" to get bucket and key.
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.markdown_uri:
        raise HTTPException(status_code=404, detail="No markdown file stored for this document")
    # Parse "s3://bucket/path/to/file.md" into bucket="bucket", key="path/to/file.md"
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
    """
    Delete a document and all its associated chunks and Qdrant vectors.

    Process:
    1. Find all chunks for this document that have been embedded (is_embedded=True).
    2. Delete their Qdrant vectors using EmbeddingService.delete_chunks().
    3. Delete all Chunk rows from Postgres.
    4. Delete the Document row from Postgres.

    Qdrant deletion is best-effort — if it fails, we log a warning but still
    complete the Postgres deletion. Stale Qdrant vectors are self-healed by
    the SyncService reconcile_with_db() check at startup.
    """
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
                doc_id, e,
                extra={"event": "chunks_delete_failed", "document_id": doc_id, "error": str(e)},
            )

    for chunk in chunks:
        db.delete(chunk)
    db.delete(doc)
    db.commit()
    # 204 No Content response — no body returned
