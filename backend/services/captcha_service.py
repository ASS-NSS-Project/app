"""
services/captcha_service.py - CAPTCHA Detection and Incident Management

When a CAPTCHA blocks our scraper, we need to:
1. Detect it reliably
2. Save evidence (screenshot)
3. Create an incident record
4. Notify a curator to resolve it

This fulfills section 9 of the spec.
"""

import logging
from datetime import datetime
from typing import Optional

from playwright.async_api import Page
from sqlalchemy.orm import Session

from config import get_settings
from models import Incident, IngestJob, IncidentType, IncidentStatus, IngestStrategy

logger = logging.getLogger(__name__)
settings = get_settings()

# Keywords that strongly indicate a CAPTCHA or block page
CAPTCHA_KEYWORDS = [
    "captcha", "recaptcha", "hcaptcha", "turnstile",
    "verify you are human", "are you a robot", "i'm not a robot",
    "prove you're human", "human verification",
    "security check", "bot detection", "access denied",
    "cloudflare ray id", "just a moment", "checking your browser",
    "enable javascript and cookies", "ddos protection",
]

# Keywords that indicate the page loaded correctly (counter-signals)
CONTENT_SIGNALS = [
    "<article", "<main", "<p>", "<h1", "<h2",
    "cookie", "privacy", "terms", "contact",
]


class CaptchaDetector:
    """
    Multi-method CAPTCHA detector.
    """

    async def detect_from_page(self, page: Page) -> bool:
        """
        Check if a loaded Playwright page is showing a CAPTCHA/block.
        Uses multiple signals for accuracy.
        """
        try:
            content = await page.content()
            title = await page.title()
            url = page.url
        except Exception:
            return False

        content_lower = content.lower()
        title_lower = title.lower()

        # Count positive CAPTCHA signals
        captcha_hits = sum(
            1 for kw in CAPTCHA_KEYWORDS
            if kw in content_lower or kw in title_lower
        )

        # Count content signals (real page content)
        content_hits = sum(
            1 for sig in CONTENT_SIGNALS
            if sig in content_lower
        )

        # If we have CAPTCHA signals and little real content, it's a CAPTCHA
        if captcha_hits >= 2 and content_hits < 3:
            logger.warning(
                f"CAPTCHA detected on {url}: "
                f"{captcha_hits} CAPTCHA signals, {content_hits} content signals"
            )
            return True

        # Cloudflare challenge pages are very short
        if "cloudflare" in content_lower and len(content) < 20000:
            if "checking your browser" in content_lower or "just a moment" in content_lower:
                return True

        return False

    def detect_from_html(self, html: str, url: str = "") -> bool:
        """
        Check HTML string for CAPTCHA signals.
        Used before page rendering.
        """
        html_lower = html.lower()
        captcha_hits = sum(1 for kw in CAPTCHA_KEYWORDS if kw in html_lower)
        content_hits = sum(1 for sig in CONTENT_SIGNALS if sig in html_lower)

        # Short page with CAPTCHA signals = probably blocked
        if captcha_hits >= 2 and len(html) < 30000 and content_hits < 5:
            logger.warning(f"CAPTCHA detected in HTML for {url}")
            return True
        return False


class CaptchaService:
    """
    Creates and manages CAPTCHA incidents.
    """

    def __init__(self, db: Session):
        self.db = db

    async def create_incident(
        self,
        job: IngestJob,
        strategy: IngestStrategy,
        detector: str,
        screenshot_uri: Optional[str] = None,
    ) -> Incident:
        """
        Create a CAPTCHA incident record in the database.
        
        This is logged according to the CAPTCHA_DETECTED event schema
        in section 9.4 of the spec.
        """
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
            f"CAPTCHA incident created: {incident.id} "
            f"for {job.url} (detector: {detector})"
        )

        return incident

    def resolve_incident(
        self,
        incident_id: str,
        resolver_user_id: str,
        resolution_note: str,
    ) -> Incident:
        """
        Mark an incident as resolved.
        After resolution, the ingest job should be retried.
        """
        incident = self.db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        incident.status = IncidentStatus.resolved
        incident.resolved_by = resolver_user_id
        incident.resolved_at = datetime.utcnow()
        incident.resolution_note = resolution_note
        self.db.commit()

        logger.info(f"Incident {incident_id} resolved by {resolver_user_id}")
        return incident

    def get_open_incidents(self, source_id: Optional[str] = None) -> list[Incident]:
        """Get all open CAPTCHA incidents, optionally filtered by source."""
        query = self.db.query(Incident).filter(
            Incident.status == IncidentStatus.open
        )
        if source_id:
            query = query.filter(Incident.source_id == source_id)
        return query.order_by(Incident.created_at.desc()).all()
