"""
services/ingest_service.py - The Core Scraping Pipeline

For every URL, the fallback chain is tried in order:
  0. API / Feed  — Jina.ai reader (clean markdown for any URL); falls back
                    internally to feedparser for RSS/Atom feeds
  1. HTML fetch  — httpx + BeautifulSoup (fast, static sites)
  2. Rendered DOM — Playwright headless Chrome (JS-heavy sites)
  3. Screenshot  — full-page screenshot → vision AI extraction

The chain stops as soon as a strategy returns text above quality_threshold_chars.
CAPTCHA detection runs at each step.
"""

import hashlib
import io
import logging
import os
import time
from datetime import datetime
from typing import Optional, Tuple

import feedparser
import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md
from playwright.async_api import async_playwright, Page
from sqlalchemy.orm import Session

from config import get_settings
from models import (
    IngestJob, Evidence, Document, Chunk,
    IngestStrategy, JobStatus, EvidenceType, ChunkType
)
from services.storage_service import StorageService
from services.extraction_service import ExtractionService
from services.captcha_service import CaptchaDetector
from services.chunking import split_prose, split_tables, split_vlm, TextChunk
from services.metrics import (
    INGEST_JOBS_TOTAL, INGEST_DURATION, CAPTCHA_INCIDENTS_TOTAL,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# CAPTCHA keywords we look for in HTML/page text
CAPTCHA_SIGNALS = [
    "captcha", "recaptcha", "hcaptcha",
    "verify you are human", "are you a robot",
    "security check", "i am not a robot",
    "prove you're human", "challenge",
    "cloudflare", "access denied",
    "403 forbidden", "bot detection",
]


class IngestService:
    """
    Orchestrates the full ingest pipeline for a single URL.
    
    Usage:
        service = IngestService(db_session)
        job = service.run(job_id)
    """

    def __init__(self, db: Session):
        self.db = db
        self.storage = StorageService()
        self.extractor = ExtractionService()
        self.captcha_detector = CaptchaDetector()

    async def run(self, job_id: str) -> IngestJob:
        """
        Main entry point. Takes a job ID, runs the pipeline, updates the DB.
        """
        job = self.db.query(IngestJob).filter(IngestJob.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.running
        job.started_at = datetime.utcnow()
        self.db.commit()

        logger.info("Ingest pipeline started", extra={
            "event": "ingest_started",
            "job_id": job.id,
            "source_id": job.source_id,
            "url": job.url,
        })

        t0 = time.monotonic()
        try:
            text, strategy, evidence_id = await self._run_pipeline(job)

            if text is None:
                job.status = JobStatus.failed
                job.error_message = "All strategies exhausted without extracting content"
                job.finished_at = datetime.utcnow()
                self.db.commit()
                INGEST_JOBS_TOTAL.labels(status="failed", strategy="unknown").inc()
                logger.error("All ingest strategies exhausted", extra={
                    "event": "ingest_failed",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "reason": "all_strategies_exhausted",
                })
                return job

            await self._create_document_and_chunks(job, text, strategy, evidence_id)

            job.status = JobStatus.done
            job.strategy_used = strategy
            job.finished_at = datetime.utcnow()
            self.db.commit()
            elapsed = time.monotonic() - t0
            strategy_val = strategy.value if strategy else "unknown"
            INGEST_JOBS_TOTAL.labels(status="done", strategy=strategy_val).inc()
            INGEST_DURATION.labels(strategy=strategy_val).observe(elapsed)
            logger.info("Ingest pipeline completed", extra={
                "event": "ingest_completed",
                "job_id": job.id,
                "source_id": job.source_id,
                "url": job.url,
                "strategy": strategy_val,
                "duration_s": round(elapsed, 2),
                "chars": len(text),
            })

        except Exception as e:
            logger.exception("Ingest pipeline crashed", extra={
                "event": "ingest_failed",
                "job_id": job.id,
                "source_id": job.source_id,
                "url": job.url,
                "reason": str(e),
            })
            job.status = JobStatus.failed
            job.error_message = str(e)
            job.finished_at = datetime.utcnow()
            self.db.commit()
            INGEST_JOBS_TOTAL.labels(status="failed", strategy="unknown").inc()

        return job

    async def _run_pipeline(
        self, job: IngestJob
    ) -> Tuple[Optional[str], Optional[IngestStrategy], Optional[str]]:
        """
        Try each strategy in order. Return (text, strategy_used, evidence_id).
        """
        source = job.source

        # Determine strategy order based on source preference
        strategies = self._get_strategy_order(source.preferred_strategy)

        for strategy in strategies:
            logger.info("Trying ingest strategy", extra={
                "event": "ingest_strategy_attempt",
                "job_id": job.id,
                "source_id": job.source_id,
                "url": job.url,
                "strategy": strategy.value,
            })
            try:
                if strategy == IngestStrategy.api:
                    result = await self._strategy_api(job)
                elif strategy == IngestStrategy.html:
                    result = await self._strategy_html(job)
                elif strategy == IngestStrategy.rendered:
                    result = await self._strategy_rendered(job)
                elif strategy == IngestStrategy.screenshot:
                    result = await self._strategy_screenshot(job)
                else:
                    continue

                if result is None:
                    continue

                text, evidence_id = result

                if len(text.strip()) >= settings.quality_threshold_chars:
                    return text, strategy, evidence_id
                else:
                    logger.info("Strategy below quality threshold, falling back", extra={
                        "event": "ingest_strategy_fallback",
                        "job_id": job.id,
                        "source_id": job.source_id,
                        "url": job.url,
                        "strategy": strategy.value,
                        "chars": len(text),
                        "threshold": settings.quality_threshold_chars,
                    })

            except CaptchaDetectedError as e:
                logger.warning("CAPTCHA detected during ingest", extra={
                    "event": "captcha_detected",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "strategy": strategy.value,
                    "detector": e.detector,
                })
                from services.captcha_service import CaptchaService
                await CaptchaService(self.db).create_incident(
                    job=job,
                    strategy=strategy,
                    detector=e.detector,
                    screenshot_uri=e.screenshot_uri,
                )
                job.status = JobStatus.captcha_blocked
                self.db.commit()
                INGEST_JOBS_TOTAL.labels(status="captcha_blocked", strategy=strategy.value).inc()
                CAPTCHA_INCIDENTS_TOTAL.labels(strategy=strategy.value).inc()
                return None, None, None

            except Exception as e:
                logger.warning("Ingest strategy error", extra={
                    "event": "ingest_strategy_error",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "strategy": strategy.value,
                    "reason": str(e),
                })
                continue

        return None, None, None

    def _get_strategy_order(self, preferred: IngestStrategy):
        """
        Returns the list of strategies to try, starting with the preferred one.
        Full chain: api → html → rendered → screenshot.
        When preferred is html/rendered/screenshot, api is skipped and the chain
        starts at that strategy, always ending with screenshot as last resort.
        """
        full_chain = [
            IngestStrategy.api,
            IngestStrategy.html,
            IngestStrategy.rendered,
            IngestStrategy.screenshot,
        ]
        if preferred in full_chain:
            idx = full_chain.index(preferred)
            return full_chain[idx:]
        return full_chain

    # ─────────────────────────────────────────────
    # STRATEGY 0: API / Feed
    # Try Jina.ai reader first — returns clean markdown for any URL.
    # Falls back to feedparser for RSS/Atom feeds.
    # ─────────────────────────────────────────────

    async def _strategy_api(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Primary: fetch https://r.jina.ai/{url} — Jina.ai converts any webpage
        to clean markdown, including JS-rendered content, without a browser.
        Secondary: feedparser for RSS/Atom feeds (if Jina.ai returns too little).
        """
        # ── Jina.ai reader ──────────────────────────────────────────────────
        jina_url = f"https://r.jina.ai/{job.url}"
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": "RAGBot/1.0 (research; contact@example.com)",
                    "Accept": "text/markdown, text/plain",
                    "X-No-Cache": "true",
                },
            ) as client:
                resp = await client.get(jina_url)

            if resp.status_code == 200:
                text = resp.text.strip()
                if len(text) >= settings.quality_threshold_chars:
                    evidence_id = await self._save_evidence(
                        job=job,
                        data=text.encode("utf-8"),
                        evidence_type=EvidenceType.html,
                        filename="jina_reader.md",
                        content_type="text/markdown",
                    )
                    return text, evidence_id
        except Exception as exc:
            logger.debug("Jina.ai reader failed, trying feedparser: %s", exc)

        # ── feedparser fallback (RSS/Atom feeds) ─────────────────────────────
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "RAGBot/1.0 (research; contact@example.com)"},
        ) as client:
            response = await client.get(job.url)

        raw = response.content
        feed = feedparser.parse(raw)

        if feed.bozo and not feed.entries:
            return None

        parts: list[str] = []
        if feed.feed.get("title"):
            parts.append(feed.feed.title)

        for entry in feed.entries[:50]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
            soup = BeautifulSoup(summary, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if title or text:
                parts.append(f"## {title}\n{text}" if title else text)

        if not parts:
            return None

        combined = "\n\n".join(parts)
        evidence_id = await self._save_evidence(
            job=job,
            data=raw,
            evidence_type=EvidenceType.html,
            filename="feed.xml",
            content_type=response.headers.get("content-type", "application/xml"),
        )
        return combined, evidence_id

    # ─────────────────────────────────────────────
    # STRATEGY 1: Simple HTML Fetch
    # Just download the HTML and extract text.
    # Fastest. Works for static sites.
    # ─────────────────────────────────────────────

    async def _strategy_html(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Download HTML, strip tags, return plain text.
        Uses httpx (async HTTP client).
        """
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": "RAGBot/1.0 (research; contact@example.com)"},
        ) as client:
            response = await client.get(job.url)

        _MAX_BODY = 20 * 1024 * 1024  # 20 MB
        if len(response.content) > _MAX_BODY:
            raise ValueError(f"Response too large: {len(response.content)} bytes")

        html = response.text

        # CAPTCHA detection in HTML
        html_lower = html.lower()
        for signal in CAPTCHA_SIGNALS:
            if signal in html_lower and len(html) < 50000:
                raise CaptchaDetectedError(
                    f"CAPTCHA signal '{signal}' found in HTML",
                    detector="html_keyword",
                )

        # Save raw HTML as evidence
        evidence_id = await self._save_evidence(
            job=job,
            data=html.encode("utf-8"),
            evidence_type=EvidenceType.html,
            filename="page.html",
            content_type="text/html",
        )

        # Parse with BeautifulSoup: remove nav, footer, scripts, ads
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        text = html_to_md(str(soup), heading_style="ATX", bullets="-", strip=["a", "img"])
        return text, evidence_id

    # ─────────────────────────────────────────────
    # STRATEGY 2: Rendered DOM (Playwright/Chrome)
    # Load the page in a real browser, wait for JS to run,
    # then extract text from the rendered DOM.
    # Works for React/Vue/Angular apps.
    # ─────────────────────────────────────────────

    async def _strategy_rendered(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Open page in headless Chrome, wait for it to render, extract text.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await browser.new_page()

            # Navigate and wait until network is quiet (no more requests)
            await page.goto(job.url, wait_until="domcontentloaded", timeout=20000)

            # CAPTCHA detection: check page content
            content = await page.content()
            content_lower = content.lower()
            for signal in CAPTCHA_SIGNALS:
                if signal in content_lower and len(content) < 50000:
                    await browser.close()
                    raise CaptchaDetectedError(
                        f"CAPTCHA signal '{signal}' in rendered DOM",
                        detector="rendered_keyword",
                    )

            # Convert rendered HTML to Markdown
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = html_to_md(str(soup), heading_style="ATX", bullets="-", strip=["a", "img"])

            # Save HTML snapshot as evidence
            evidence_id = await self._save_evidence(
                job=job,
                data=content.encode("utf-8"),
                evidence_type=EvidenceType.dom,
                filename="rendered_dom.html",
                content_type="text/html",
            )

            await browser.close()
            return text, evidence_id

    # ─────────────────────────────────────────────
    # STRATEGY 3: Screenshot + AI Vision Extraction
    # Take a full-page screenshot, send to Claude vision model.
    # Works even for canvas, images, complex layouts.
    # ─────────────────────────────────────────────

    async def _strategy_screenshot(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Take a screenshot, send to Claude claude-sonnet-4-6 vision model to extract text.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await page.goto(job.url, wait_until="domcontentloaded", timeout=20000)

            # Check for CAPTCHA in the screenshot itself
            is_captcha = await self.captcha_detector.detect_from_page(page)
            if is_captcha:
                # Save the CAPTCHA screenshot as evidence before raising
                screenshot_bytes = await page.screenshot(full_page=False)
                screenshot_uri = await self._save_evidence(
                    job=job,
                    data=screenshot_bytes,
                    evidence_type=EvidenceType.screenshot,
                    filename="captcha_page.png",
                    content_type="image/png",
                )
                await browser.close()
                raise CaptchaDetectedError(
                    "CAPTCHA detected in screenshot",
                    detector="screenshot_classifier",
                    screenshot_uri=screenshot_uri,
                )

            # Take full-page screenshot
            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

        # Save screenshot as evidence
        evidence_id = await self._save_evidence(
            job=job,
            data=screenshot_bytes,
            evidence_type=EvidenceType.screenshot,
            filename="full_page.png",
            content_type="image/png",
        )

        # Send screenshot to Claude vision to extract text and structure
        text = await self.extractor.extract_from_screenshot(
            screenshot_bytes=screenshot_bytes,
            url=job.url,
        )

        return text, evidence_id

    # ─────────────────────────────────────────────
    # HELPER: Save evidence file to MinIO
    # ─────────────────────────────────────────────

    async def _save_evidence(
        self,
        job: IngestJob,
        data: bytes,
        evidence_type: EvidenceType,
        filename: str,
        content_type: str,
    ) -> str:
        """
        Save a file to MinIO, create an Evidence record, return evidence ID.
        """
        # Create a unique storage path
        file_hash = hashlib.sha256(data).hexdigest()
        storage_key = f"{job.source_id}/{job.id}/{filename}"

        # Upload to S3-compatible storage
        self.storage.upload(
            bucket=settings.s3_bucket_evidence,
            key=storage_key,
            data=data,
            content_type=content_type,
        )

        # Record in DB
        evidence = Evidence(
            job_id=job.id,
            type=evidence_type,
            storage_uri=storage_key,
            file_hash=file_hash,
            file_size_bytes=len(data),
        )
        self.db.add(evidence)
        self.db.commit()
        self.db.refresh(evidence)

        return evidence.id

    # ─────────────────────────────────────────────
    # HELPER: Create Document and split into Chunks
    # ─────────────────────────────────────────────

    async def _create_document_and_chunks(
        self,
        job: IngestJob,
        text: str,
        strategy: IngestStrategy,
        evidence_id: Optional[str],
    ):
        """
        Store the extracted text as a Document, split into Chunks.
        Chunks are what gets embedded and stored in Qdrant.
        """
        content_hash = hashlib.sha256(text.encode()).hexdigest()

        # Check if we already have this exact content (deduplication)
        existing = (
            self.db.query(Document)
            .filter(
                Document.source_id == job.source_id,
                Document.url == job.url,
                Document.content_hash == content_hash,
            )
            .first()
        )
        if existing:
            logger.info(f"Document for {job.url} unchanged (same hash), skipping")
            return

        # Get or create document (increment version if URL already exists)
        prev = (
            self.db.query(Document)
            .filter(Document.source_id == job.source_id, Document.url == job.url)
            .order_by(Document.doc_version.desc())
            .first()
        )
        version = (prev.doc_version + 1) if prev else 1

        # Extract title from text (first non-empty line)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0][:200] if lines else job.url

        doc = Document(
            source_id=job.source_id,
            url=job.url,
            title=title,
            doc_version=version,
            quality_score=min(1.0, len(text) / 5000),  # Simple proxy
            ingest_strategy=strategy,
            content_hash=content_hash,
            content_markdown=text,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        # Pick chunker based on strategy
        source_method = strategy.value if strategy else "html"
        all_chunks: list[TextChunk] = []

        if strategy == IngestStrategy.screenshot:
            all_chunks = split_vlm(text)
        else:
            # For HTML and rendered strategies: extract tables first, then prose
            table_chunks = split_tables(text, source_method=source_method)
            prose_chunks = split_prose(text, source_method=source_method)
            all_chunks = table_chunks + prose_chunks

        for idx, tc in enumerate(all_chunks):
            chunk = Chunk(
                document_id=doc.id,
                chunk_type=tc.chunk_type,
                text=tc.text,
                chunk_index=idx,
                citation_url=job.url,
                citation_evidence_id=evidence_id,
                section_path=tc.section_path,
                token_count=tc.token_count,
                source_method=tc.source_method or source_method,
            )
            self.db.add(chunk)

        self.db.commit()
        logger.info("Document created with chunks", extra={
            "event": "document_created",
            "job_id": job.id,
            "source_id": job.source_id,
            "url": job.url,
            "document_id": doc.id,
            "chunk_count": len(all_chunks),
            "strategy": strategy.value if strategy else "unknown",
        })


class CaptchaDetectedError(Exception):
    """Raised when CAPTCHA is detected during any ingest strategy."""
    def __init__(self, message: str, detector: str, screenshot_uri: str = None):
        super().__init__(message)
        self.detector = detector
        self.screenshot_uri = screenshot_uri
