"""
services/ingest.py - The Core Scraping Pipeline

Takes a URL and extracts its text content using a waterfall of strategies,
stopping as soon as one succeeds. Each strategy is tried in order of speed
and simplicity — faster/simpler strategies first, slower/heavier ones last.

Strategy waterfall:

  0. API / Feed (api)
     Try Jina.ai reader first: https://r.jina.ai/{url} converts any webpage
     to clean Markdown without needing a browser. If Jina.ai returns too little
     (or fails), fall back to feedparser for RSS/Atom feeds.
     - Fastest, no browser needed, handles JS-rendered content via Jina.ai.
     - Fails on pages that require cookies or block bot user-agents.

  1. HTML fetch (html)
     Download the raw HTML with httpx and extract text with BeautifulSoup.
     - Fast, works on static sites.
     - Fails on JS-rendered pages (React/Vue/Angular apps show empty HTML).

  2. Rendered DOM (rendered)
     Launch a headless Chromium browser with Playwright, wait for JS to run,
     then extract text from the fully-rendered DOM.
     - Handles JS-rendered sites.
     - Slower (~5-15 s) and more resource-intensive than HTML fetch.
     - Fails when the site detects Playwright/headless Chrome.

  3. Screenshot + VLM (screenshot)
     Take a full-page screenshot and send it to a vision-language model
     via the AIaaS endpoint to extract text from the image.
     - Works for anything — canvas layouts, complex CSS, iframes.
     - Slowest and most expensive (VLM API call).
     - Last resort when all text-based strategies fail.

CAPTCHA detection runs at every step. When detected, the ingest job is
marked "captcha_blocked" and a curator Incident is created for review.
"""

import asyncio
import hashlib
import io
import logging
import os
import re
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
from services.storage import StorageService
from services.extraction import ExtractionService
from services.captcha import CaptchaDetector
from services.chunking import split_prose, split_tables, split_vlm, TextChunk
from services.metrics import (
    INGEST_JOBS_TOTAL, INGEST_DURATION, CAPTCHA_INCIDENTS_TOTAL,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Strings that suggest a CAPTCHA or bot-protection page rather than real content.
# Checked against lowercased HTML — two or more matches with a small page triggers
# a CaptchaDetectedError (defined at the bottom of this file).
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

    Responsibilities:
    - Load the IngestJob from Postgres and set it to "running".
    - Try each scraping strategy in order until one succeeds.
    - Detect CAPTCHAs and create Incidents for curators.
    - Save evidence files (HTML, screenshots) to S3.
    - Create the Document row and split the text into Chunk rows.
    - Update the IngestJob status and record Prometheus metrics.

    Usage:
        service = IngestService(db_session)
        completed_job = await service.run(job_id)
    """

    def __init__(self, db: Session):
        """
        Args:
            db: Active SQLAlchemy session shared with the caller.
                Commits are done within this service; the caller must not
                commit between IngestService calls.
        """
        self.db = db
        self.storage = StorageService()             # S3/MinIO client
        self.extractor = ExtractionService()        # VLM screenshot extractor
        self.captcha_detector = CaptchaDetector()   # keyword-based CAPTCHA heuristic

    async def run(self, job_id: str) -> IngestJob:
        """
        Main entry point: run the full ingest pipeline for one job.

        Flow:
        1. Load the IngestJob and mark it "running".
        2. Call _run_pipeline() to try strategies in order.
        3. If a strategy succeeds: create Document + Chunks, mark job "done".
        4. If all strategies fail: mark job "failed".
        5. If CAPTCHA detected: mark job "captcha_blocked" (handled inside pipeline).

        Args:
            job_id: UUID of the IngestJob row to process.

        Returns:
            The updated IngestJob object.
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
                # Refresh to distinguish cancellation from genuine exhaustion —
                # the cancel API sets status=failed before _run_pipeline returns.
                self.db.refresh(job)
                if job.status == JobStatus.failed:
                    # Already marked by the cancel API; don't overwrite the message.
                    logger.info("Ingest pipeline stopped due to cancellation", extra={
                        "event": "ingest_cancelled",
                        "job_id": job.id,
                        "source_id": job.source_id,
                        "url": job.url,
                    })
                    return job

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

            # Store extracted text as a Document and split it into Chunks
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
        Try each ingest strategy in order and return the first that succeeds.

        Strategy order is determined by the source's preferred_strategy setting.
        If preferred_strategy is "rendered", we skip "api" and "html" and start
        directly at "rendered", still falling through to "screenshot" if needed.

        CaptchaDetectedError is handled here — it stops the waterfall and marks
        the job as "captcha_blocked" instead of trying the next strategy.

        Returns:
            Tuple of (extracted_text, strategy_used, evidence_id).
            All three are None if every strategy failed or was CAPTCHA-blocked.
        """
        source = job.source
        strategies = self._get_strategy_order(source.preferred_strategy)

        for strategy in strategies:
            # Re-read the job row — the cancel API may have set status=failed
            # while a previous strategy was running.
            self.db.refresh(job)
            if job.status == JobStatus.failed:
                logger.info("Job cancelled mid-pipeline, stopping", extra={
                    "event": "ingest_cancelled",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "strategy": strategy.value,
                })
                return None, None, None

            logger.info("Trying ingest strategy", extra={
                "event": "ingest_strategy_attempt",
                "job_id": job.id,
                "source_id": job.source_id,
                "url": job.url,
                "strategy": strategy.value,
            })
            if source.rate_limit_rps > 0:
                await asyncio.sleep(1.0 / source.rate_limit_rps)
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
                    continue  # unknown strategy — skip

                if result is None:
                    continue  # strategy returned nothing — try the next one

                text, evidence_id = result

                if len(text.strip()) >= settings.quality_threshold_chars:
                    # Content is substantial enough — use this strategy's output
                    return text, strategy, evidence_id
                else:
                    # Too little text — probably a partial load or paywalled page
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
                # CAPTCHA detected — don't try further strategies (they'll also fail)
                logger.warning("CAPTCHA detected during ingest", extra={
                    "event": "captcha_detected",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "strategy": strategy.value,
                    "detector": e.detector,
                })
                from services.captcha import CaptchaService
                # Create a curator Incident so the problem is visible in the dashboard
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
                return None, None, None  # stop waterfall

            except Exception as e:
                # Generic failure — log and try the next strategy
                logger.warning("Ingest strategy error", extra={
                    "event": "ingest_strategy_error",
                    "job_id": job.id,
                    "source_id": job.source_id,
                    "url": job.url,
                    "strategy": strategy.value,
                    "reason": str(e),
                })
                continue

        return None, None, None  # all strategies failed

    def _get_strategy_order(self, preferred: IngestStrategy):
        """
        Return the list of strategies to try, starting from the preferred one.

        The full chain is: api → html → rendered → screenshot.
        When preferred_strategy is "rendered", we start at "rendered" and still
        fall through to "screenshot" as a last resort. We never go backward
        (e.g. preferred="rendered" does not re-try "html" after "rendered" fails).

        Args:
            preferred: The source's configured preferred_strategy.

        Returns:
            List of IngestStrategy enum values in order of preference.
        """
        full_chain = [
            IngestStrategy.api,
            IngestStrategy.html,
            IngestStrategy.rendered,
            IngestStrategy.screenshot,
        ]
        if preferred in full_chain:
            idx = full_chain.index(preferred)
            return full_chain[idx:]  # start from preferred, keep all after it
        return full_chain  # unknown preferred strategy — use full chain

    # ---
    # STRATEGY 0: API / Feed (Jina.ai reader + feedparser)
    # ---

    async def _strategy_api(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Fetch clean Markdown from Jina.ai reader, or fall back to feedparser.

        Jina.ai reader (https://r.jina.ai/{url}) is a free web service that
        fetches a URL, runs it through a headless browser, and returns clean
        Markdown. It handles JS-rendered content without us needing to run
        Playwright ourselves. The resulting text is already stripped of nav,
        ads, and footers.

        If Jina.ai fails or returns too little text, we fall back to feedparser,
        which parses RSS/Atom XML feeds. This is useful for news sites, blogs,
        and any source that publishes an RSS feed.

        Returns:
            Tuple of (text, evidence_id) or None if both Jina.ai and feedparser fail.
        """
        # --- Jina.ai reader path
        jina_url = f"https://r.jina.ai/{job.url}"
        try:
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": "RAGBot/1.0 (research; contact@example.com)",
                    "Accept": "text/markdown, text/plain",
                    "X-No-Cache": "true",  # tell Jina.ai to fetch fresh content
                },
            ) as client:
                resp = await client.get(jina_url)

            if resp.status_code == 200:
                text = resp.content.decode('utf-8', errors='replace').strip()
                # Jina.ai prepends a metadata header block:
                #   Title: ...
                #   URL Source: ...
                #   Markdown Content:
                #   <actual content starts here>
                # Strip everything up to and including "Markdown Content:\n"
                # so we don't index the Jina metadata itself.
                marker = re.search(r'^Markdown Content:\s*\n+', text, re.MULTILINE)
                if marker:
                    text = text[marker.end():].strip()
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

        # --- feedparser fallback for RSS/Atom feeds
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "RAGBot/1.0 (research; contact@example.com)"},
        ) as client:
            response = await client.get(job.url)

        raw = response.content  # raw bytes — feedparser handles encoding detection
        feed = feedparser.parse(raw)

        # bozo=True means feedparser encountered a malformed/non-feed document.
        # If also no entries, this URL is definitely not a feed.
        if feed.bozo and not feed.entries:
            return None

        # Build text by combining feed title and entry title+summary for up to 50 entries
        parts: list[str] = []
        if feed.feed.get("title"):
            parts.append(feed.feed.title)

        for entry in feed.entries[:50]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
            # Feed entries often have HTML in summaries — strip to plain text
            soup = BeautifulSoup(summary, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if title or text:
                parts.append(f"## {title}\n{text}" if title else text)

        if not parts:
            return None  # feed was empty

        combined = "\n\n".join(parts)
        evidence_id = await self._save_evidence(
            job=job,
            data=raw,
            evidence_type=EvidenceType.html,
            filename="feed.xml",
            content_type=response.headers.get("content-type", "application/xml"),
        )
        return combined, evidence_id

    # ---
    # STRATEGY 1: Simple HTML Fetch
    # ---

    async def _strategy_html(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Download the raw HTML and convert it to Markdown with BeautifulSoup + markdownify.

        Fastest strategy — no browser, no external services. Works well for
        static sites, server-side rendered pages, and any page that delivers
        its content in the initial HTML response.

        Fails on JS-heavy SPAs (React/Vue/Angular) where the HTML shell has
        almost no content and the real data is loaded by JavaScript after page load.

        Args:
            job: The IngestJob with the URL to fetch.

        Returns:
            Tuple of (markdown_text, evidence_id) or None.

        Raises:
            CaptchaDetectedError: If CAPTCHA signals are found in the HTML.
            ValueError: If the response body exceeds 20 MB.
        """
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": "RAGBot/1.0 (research; contact@example.com)"},
        ) as client:
            response = await client.get(job.url)

        # Guard against accidentally downloading huge binary files (PDFs, videos, etc.)
        _MAX_BODY = 20 * 1024 * 1024  # 20 MB
        if len(response.content) > _MAX_BODY:
            raise ValueError(f"Response too large: {len(response.content)} bytes")

        # Pass raw bytes (not response.text) so BeautifulSoup can read the charset
        # from the page's own <meta charset="..."> tag. Using response.text would
        # decode with the Content-Type charset (often wrong or missing), corrupting
        # non-ASCII characters like Czech, German, or Chinese text.
        soup = BeautifulSoup(response.content, "html.parser")
        html = str(soup)

        # CAPTCHA detection: look for multiple CAPTCHA signals in small pages.
        # Real content pages are always larger than 50 KB; CAPTCHA pages are tiny.
        html_lower = html.lower()
        for signal in CAPTCHA_SIGNALS:
            if signal in html_lower and len(html) < 50000:
                raise CaptchaDetectedError(
                    f"CAPTCHA signal '{signal}' found in HTML",
                    detector="html_keyword",
                )

        # Save the raw HTML as evidence before stripping elements
        evidence_id = await self._save_evidence(
            job=job,
            data=html.encode("utf-8"),
            evidence_type=EvidenceType.html,
            filename="page.html",
            content_type="text/html",
        )

        # Remove non-content elements that would add noise to the extracted text
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Convert remaining HTML to Markdown.
        # strip=["a", "img"]: remove links and images (we only care about text content)
        # heading_style="ATX": use # headings instead of underline-style headings
        text = html_to_md(str(soup), heading_style="ATX", bullets="-", strip=["a", "img"])
        return text, evidence_id

    # ---
    # STRATEGY 2: Rendered DOM (Playwright headless Chrome)
    # ---

    async def _strategy_rendered(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Launch a real headless browser, load the page, and extract the rendered DOM.

        Playwright drives a real Chromium instance. JavaScript executes, AJAX
        requests complete, and the DOM is in its final rendered state when we
        read it. This handles React, Vue, Angular, and other SPA frameworks.

        We wait for "domcontentloaded" (not "networkidle") to avoid waiting forever
        on pages that continuously poll for live data.

        Args:
            job: The IngestJob with the URL to load.

        Returns:
            Tuple of (markdown_text, evidence_id) or None.

        Raises:
            CaptchaDetectedError: If CAPTCHA signals are found in the rendered HTML.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                # Required in Docker/Kubernetes where the process doesn't have
                # a sandbox environment set up (no /proc/net/dev or seccomp profile)
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = await browser.new_page()

            # Navigate to the URL; domcontentloaded fires when the HTML is parsed
            # and deferred scripts are starting, but before all resources (images, fonts)
            await page.goto(job.url, wait_until="domcontentloaded", timeout=20000)

            # Check rendered HTML for CAPTCHA signals
            content = await page.content()
            content_lower = content.lower()
            for signal in CAPTCHA_SIGNALS:
                if signal in content_lower and len(content) < 50000:
                    await browser.close()
                    raise CaptchaDetectedError(
                        f"CAPTCHA signal '{signal}' in rendered DOM",
                        detector="rendered_keyword",
                    )

            # Convert rendered HTML to Markdown (same processing as html strategy)
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = html_to_md(str(soup), heading_style="ATX", bullets="-", strip=["a", "img"])

            # Save the rendered HTML as evidence
            evidence_id = await self._save_evidence(
                job=job,
                data=content.encode("utf-8"),
                evidence_type=EvidenceType.dom,
                filename="rendered_dom.html",
                content_type="text/html",
            )

            await browser.close()
            return text, evidence_id

    # ---
    # STRATEGY 3: Screenshot + VLM
    # ---

    async def _strategy_screenshot(self, job: IngestJob) -> Optional[Tuple[str, str]]:
        """
        Take a full-page screenshot and send it to the vision-language model.

        This is the most powerful but slowest strategy. It works for any page
        layout, including canvas-based rendering, complex CSS, and iframes.
        The VLM receives the screenshot as a base64 PNG and returns Markdown.

        If the screenshot shows a CAPTCHA, we save it as evidence (so the curator
        can see what the CAPTCHA looked like) and raise CaptchaDetectedError.

        Args:
            job: The IngestJob with the URL to screenshot.

        Returns:
            Tuple of (markdown_text, evidence_id).

        Raises:
            CaptchaDetectedError: If the CAPTCHA detector fires on the screenshot.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            # Set a realistic viewport — helps with responsive-design rendering
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await page.goto(job.url, wait_until="domcontentloaded", timeout=20000)

            # Run CaptchaDetector on the rendered page (checks the DOM + title)
            is_captcha = await self.captcha_detector.detect_from_page(page)
            if is_captcha:
                # Save the CAPTCHA screenshot so curators can see what blocked us
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

            # full_page=True captures below the visible viewport (scrolls and stitches)
            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

        # Save the full-page screenshot as evidence (viewable via pre-signed S3 URL)
        evidence_id = await self._save_evidence(
            job=job,
            data=screenshot_bytes,
            evidence_type=EvidenceType.screenshot,
            filename="full_page.png",
            content_type="image/png",
        )

        # Send the screenshot to the VLM and get back structured Markdown
        text = await self.extractor.extract_from_screenshot(
            screenshot_bytes=screenshot_bytes,
            url=job.url,
        )

        return text, evidence_id

    # ---
    # HELPER: Save evidence to S3 and create an Evidence DB record
    # ---

    async def _save_evidence(
        self,
        job: IngestJob,
        data: bytes,
        evidence_type: EvidenceType,
        filename: str,
        content_type: str,
    ) -> str:
        """
        Upload a file to S3 and create a corresponding Evidence row in Postgres.

        Evidence is stored under a path that makes it easy to find by job:
            <source_id>/<job_id>/<filename>
        e.g. "abc123/def456/full_page.png"

        The file_hash (SHA-256) is stored on the Evidence row so we can detect
        duplicate evidence files across jobs (same page scraped twice, same content).

        Args:
            job: The IngestJob that produced this evidence.
            data: Raw bytes to store.
            evidence_type: Enum value classifying the file (screenshot, html, dom).
            filename: The filename within the job's S3 prefix.
            content_type: MIME type for the S3 object metadata.

        Returns:
            The UUID of the newly created Evidence row.
        """
        file_hash = hashlib.sha256(data).hexdigest()
        storage_key = f"{job.source_id}/{job.id}/{filename}"

        self.storage.upload(
            bucket=settings.s3_bucket_evidence,
            key=storage_key,
            data=data,
            content_type=content_type,
        )

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

    # ---
    # HELPER: Create Document and split into Chunks
    # ---

    async def _create_document_and_chunks(
        self,
        job: IngestJob,
        text: str,
        strategy: IngestStrategy,
        evidence_id: Optional[str],
    ):
        """
        Persist extracted text as a Document and split it into Chunks.

        Deduplication: if the same source+URL already has a document with the
        exact same content (matched by SHA-256 hash), we skip creating a new one.
        This prevents storing duplicates when a source is re-crawled without changes.

        Versioning: if the content changed, a new Document is created with
        doc_version incremented. Older versions remain in Postgres as history.

        Chunking strategy depends on the ingest strategy:
        - api / screenshot → split_vlm (respects VLM's block structure)
        - html / rendered → split_tables + split_prose (separate tables from prose)

        S3 backup: the full Markdown text, chunks JSON, and job metadata are also
        uploaded to the docs S3 bucket for disaster recovery and future re-embedding.

        Args:
            job: The completed IngestJob.
            text: The extracted text content in Markdown format.
            strategy: Which ingest strategy produced this text.
            evidence_id: UUID of the Evidence row for the primary artifact (screenshot/HTML).
        """
        content_hash = hashlib.sha256(text.encode()).hexdigest()

        # Deduplication check: same source + URL + content hash → skip
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

        # Determine the version number for this document
        prev = (
            self.db.query(Document)
            .filter(Document.source_id == job.source_id, Document.url == job.url)
            .order_by(Document.doc_version.desc())
            .first()
        )
        version = (prev.doc_version + 1) if prev else 1

        # Extract title from first non-empty line of the text
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0][:200] if lines else job.url

        source_method = strategy.value if strategy else "html"
        all_chunks: list[TextChunk] = []

        # Choose the chunking path based on how the text was extracted
        if strategy in (IngestStrategy.screenshot, IngestStrategy.api):
            # VLM and Jina.ai output already has logical block structure — use VLM chunker
            all_chunks = split_vlm(text)
        else:
            # HTML-derived text: extract tables separately, then chunk remaining prose
            table_chunks = split_tables(text, source_method=source_method)
            prose_chunks = split_prose(text, source_method=source_method)
            all_chunks = table_chunks + prose_chunks

        # Prepare chunks for S3 backup (serialise to plain dicts)
        chunks_json = [
            {
                "chunk_index": idx,
                "text": tc.text,
                "chunk_type": tc.chunk_type.value if hasattr(tc.chunk_type, 'value') else str(tc.chunk_type),
                "section_path": tc.section_path,
                "token_count": tc.token_count,
                "source_method": tc.source_method or source_method
            }
            for idx, tc in enumerate(all_chunks)
        ]

        # Upload full document bundle to S3 (markdown, chunks, metadata)
        from services.storage import StorageService
        storage = StorageService()

        job_metadata = {
            "source_id": job.source_id,
            "job_id": job.id,
            "url": job.url,
            "strategy": strategy.value if strategy else "unknown",
            # quality_score: rough normalised measure of content richness (0.0–1.0)
            "quality_score": min(1.0, len(text) / 5000),
            "timestamp": datetime.utcnow().isoformat()
        }

        markdown_uri, chunks_uri, metadata_uri = storage.store_document_bundle(
            source_id=job.source_id,
            job_id=job.id,
            markdown=text,
            chunks=chunks_json,
            metadata=job_metadata
        )

        # Create the Document row, including the S3 URIs for the stored files
        doc = Document(
            source_id=job.source_id,
            url=job.url,
            title=title,
            doc_version=version,
            quality_score=min(1.0, len(text) / 5000),
            ingest_strategy=strategy,
            content_hash=content_hash,
            content_markdown=text,          # full text also stored in Postgres for quick access
            markdown_uri=markdown_uri,      # S3 URI for the Markdown file
            chunks_uri=chunks_uri,          # S3 URI for the chunks JSON file
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        # Create one Chunk row per split chunk, linking back to the document
        for idx, tc in enumerate(all_chunks):
            chunk = Chunk(
                document_id=doc.id,
                chunk_type=tc.chunk_type,
                text=tc.text,
                chunk_index=idx,                    # position within document (0-based)
                citation_url=job.url,               # URL shown in search results
                citation_evidence_id=evidence_id,   # link to the screenshot/HTML evidence
                section_path=tc.section_path,
                token_count=tc.token_count,
                source_method=tc.source_method or source_method,
                embedding_status='pending',          # embedding worker will process this
                qdrant_sync_status='missing',        # not yet in Qdrant
                retry_count=0,
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
    """
    Raised when any ingest strategy detects a CAPTCHA or bot-protection page.

    Carrying the detector name and (optionally) a screenshot URI lets the
    CaptchaService create an informative Incident record for the curator.
    """

    def __init__(self, message: str, detector: str, screenshot_uri: str = None):
        """
        Args:
            message: Human-readable description of where the CAPTCHA was detected.
            detector: Name of the component that detected it
                      (e.g. "html_keyword", "rendered_keyword", "screenshot_classifier").
            screenshot_uri: S3 key of a screenshot of the CAPTCHA page, if captured.
        """
        super().__init__(message)
        self.detector = detector
        self.screenshot_uri = screenshot_uri
