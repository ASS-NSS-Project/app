"""
services/captcha.py - CAPTCHA Detection and Incident Management

When a scraping attempt is blocked by a CAPTCHA or bot-protection system,
this module detects the block, records evidence, and creates an incident
for a human curator to review.

Detection strategy:
- Keyword scan: looks for known CAPTCHA-related text in the page HTML/title
- Structural scan: checks whether the page has real content (articles, paragraphs)
- Cloudflare heuristic: short pages with "just a moment" are Cloudflare challenges

A detection fires only when 2+ CAPTCHA keywords are present AND real content
signals are absent — this avoids false positives on pages that merely *mention*
CAPTCHAs (e.g. a blog post about web scraping).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import Page
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config import get_settings
from models import Incident, IngestJob, IncidentType, IncidentStatus, IngestStrategy

logger = logging.getLogger(__name__)
settings = get_settings()

# Strings that appear on CAPTCHA and bot-protection pages.
# Each entry is a substring — checked case-insensitively against the full page HTML.
CAPTCHA_KEYWORDS = [
    "captcha", "recaptcha", "hcaptcha", "turnstile",
    "verify you are human", "are you a robot", "i'm not a robot",
    "prove you're human", "human verification",
    "security check", "bot detection", "access denied",
    "cloudflare ray id", "just a moment", "checking your browser",
    "enable javascript and cookies", "ddos protection",
]

# Strings that indicate the page has real content — their presence reduces the
# likelihood of a false-positive CAPTCHA detection.
CONTENT_SIGNALS = [
    "<article", "<main", "<p>", "<h1", "<h2",
    "cookie", "privacy", "terms", "contact",
]


class CaptchaDetector:
    """
    Detects whether a page response is a CAPTCHA challenge rather than real content.

    Two detection methods are provided:
    - detect_from_page(): for use after Playwright renders the page (async)
    - detect_from_html(): for use after a raw HTTP fetch (sync)
    """

    async def detect_from_page(self, page: Page) -> bool:
        """
        Check whether a rendered Playwright page is showing a CAPTCHA or bot challenge.

        Reads the full rendered HTML, page title, and current URL from the browser,
        then applies the keyword + content-signal heuristic.

        Args:
            page: An active Playwright Page object with the target URL already loaded.

        Returns:
            True if a CAPTCHA or bot challenge was detected, False otherwise.
        """
        try:
            content = await page.content()
            title   = await page.title()
            url     = page.url
        except Exception:
            # If we can't even read the page content, don't block the scrape
            return False

        content_lower = content.lower()
        title_lower   = title.lower()

        # Count how many CAPTCHA keywords appear in the page content or title
        captcha_hits = sum(
            1 for kw in CAPTCHA_KEYWORDS
            if kw in content_lower or kw in title_lower
        )

        # Count how many real-content structural signals are present
        content_hits = sum(
            1 for sig in CONTENT_SIGNALS
            if sig in content_lower
        )

        # Require 2+ CAPTCHA signals AND fewer than 3 content signals.
        # A single mention of "captcha" could appear in any article about web scraping.
        # A real CAPTCHA page has no <article>, <main>, or <p> tags — it's always sparse HTML.
        if captcha_hits >= 2 and content_hits < 3:
            logger.warning(
                f"CAPTCHA detected on {url}: "
                f"{captcha_hits} CAPTCHA signals, {content_hits} content signals"
            )
            return True

        # Cloudflare challenge pages are very short and always contain "just a moment"
        # or "checking your browser" — catch these even if they miss the 2-hit threshold.
        if "cloudflare" in content_lower and len(content) < 20000:
            if "checking your browser" in content_lower or "just a moment" in content_lower:
                return True

        return False

    def detect_from_html(self, html: str, url: str = "") -> bool:
        """
        Check raw HTML content for CAPTCHA signals.

        Used by the HTML ingest strategy (before Playwright rendering) to catch
        blocks early and avoid unnecessary browser launches.

        Args:
            html: The raw HTML string returned by the HTTP request.
            url: The URL that was fetched (used only for logging).

        Returns:
            True if a CAPTCHA or bot challenge was detected, False otherwise.
        """
        html_lower   = html.lower()
        captcha_hits = sum(1 for kw in CAPTCHA_KEYWORDS if kw in html_lower)
        content_hits = sum(1 for sig in CONTENT_SIGNALS if sig in html_lower)

        # len < 30000 replaces the DOM structural check — CAPTCHA pages are always tiny.
        # content_hits < 5 allows for pages that have both some content and a CAPTCHA overlay.
        if captcha_hits >= 2 and len(html) < 30000 and content_hits < 5:
            logger.warning(f"CAPTCHA detected in HTML for {url}")
            return True

        return False


class CaptchaService:
    """
    Creates and manages CAPTCHA incidents in the database.

    Responsibilities:
    - Create incident records when a CAPTCHA is detected
    - Suppress duplicate incidents (open or within the source's crawl-frequency window)
    - Mark incidents as resolved when a curator handles them
    - List open incidents for the incidents management UI
    """

    def __init__(self, db: Session):
        """
        Args:
            db: Active SQLAlchemy database session shared with the caller.
        """
        self.db = db

    async def create_incident(
        self,
        job: IngestJob,
        strategy: IngestStrategy,
        detector: str,
        screenshot_uri: Optional[str] = None,
    ) -> Incident:
        """
        Create a CAPTCHA incident record for a blocked ingest job.

        Automatically suppresses duplicates in two cases:
        1. An open incident already exists for this source+URL (curator has not resolved it).
        2. A recent incident exists within the source's crawl_frequency_hours window
           (prevents a burst of identical incidents if the same URL is retried rapidly).

        Args:
            job: The IngestJob that was blocked by the CAPTCHA.
            strategy: The scraping strategy that was in use when the block was detected.
            detector: Name of the component that detected the CAPTCHA (e.g. "captcha_service").
            screenshot_uri: S3 path to a screenshot of the CAPTCHA page, if captured.

        Returns:
            The newly created Incident, or an existing suppressed one.
        """
        # Calculate the deduplication window from the source's crawl frequency
        source = getattr(job, 'source', None)
        cooldown_hours = source.crawl_frequency_hours if source else 2
        cutoff = datetime.utcnow() - timedelta(hours=cooldown_hours)

        # Check for an existing open or recent incident for this source+URL
        existing = self.db.query(Incident).filter(
            Incident.source_id == job.source_id,
            Incident.url == job.url,
            or_(
                Incident.status == IncidentStatus.open,
                Incident.created_at >= cutoff,
            ),
        ).first()

        if existing:
            logger.info(
                "Incident suppressed for %s (open or within %dh cooldown)",
                job.url, cooldown_hours,
                extra={"event": "captcha_incident_dedup", "incident_id": existing.id, "url": job.url},
            )
            return existing

        incident = Incident(
            type=IncidentType.captcha,
            source_id=job.source_id,
            url=job.url,
            strategy=strategy,
            severity="medium",
            status=IncidentStatus.open,
            detector=detector,
            evidence_screenshot_uri=screenshot_uri,
        )
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)

        logger.warning(
            f"CAPTCHA incident created: {incident.id} for {job.url} (detector: {detector})"
        )
        return incident

    def resolve_incident(
        self,
        incident_id: str,
        resolver_user_id: str,
        resolution_note: str,
    ) -> Incident:
        """
        Mark an incident as resolved by a curator.

        After resolution, the source will be retried on the next scheduler tick.

        Args:
            incident_id: UUID of the incident to resolve.
            resolver_user_id: UUID of the curator who resolved it (for the audit trail).
            resolution_note: Free-text explanation of what was done (e.g. "IP rotated").

        Returns:
            The updated Incident object.

        Raises:
            ValueError: If no incident with incident_id exists.
        """
        incident = self.db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        incident.status          = IncidentStatus.resolved
        incident.resolved_by     = resolver_user_id
        incident.resolved_at     = datetime.utcnow()
        incident.resolution_note = resolution_note
        self.db.commit()

        logger.info(f"Incident {incident_id} resolved by {resolver_user_id}")
        return incident

    def get_open_incidents(self, source_id: Optional[str] = None) -> list[Incident]:
        """
        Return all open (unresolved) incidents, newest first.

        Args:
            source_id: Optional UUID to filter incidents for a specific source.

        Returns:
            List of Incident objects with status=open.
        """
        query = self.db.query(Incident).filter(Incident.status == IncidentStatus.open)
        if source_id:
            query = query.filter(Incident.source_id == source_id)
        return query.order_by(Incident.created_at.desc()).all()
