"""
services/extraction_service.py - AI Vision Extraction

When a webpage can't be read as text, we take a screenshot
and send it to Claude claude-sonnet-4-6 (which has vision capabilities).

Claude looks at the image and extracts:
- Headings and structure
- Paragraphs of text
- Tables (converted to text)
- Lists

This is the "AI extractor" described in section 5.3 of the spec.
"""

import base64
import logging
from typing import Optional

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ExtractionService:
    """
    Uses Claude vision to extract structured text from screenshots.
    """

    def __init__(self):
        # Initialize the Anthropic client
        # It automatically uses the ANTHROPIC_API_KEY environment variable
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def extract_from_screenshot(
        self,
        screenshot_bytes: bytes,
        url: str,
    ) -> str:
        """
        Send a screenshot to Claude vision and get back structured text.
        
        Claude will:
        1. Read all text visible in the image
        2. Identify the structure (headings, paragraphs, tables)
        3. Return clean, structured text
        
        Args:
            screenshot_bytes: PNG/JPEG image as bytes
            url: The URL this screenshot came from (for context)
        
        Returns:
            Extracted text as a string
        """
        # Convert image bytes to base64
        # The API requires images in base64 format
        image_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

        logger.info(f"Sending screenshot to Claude vision for URL: {url}")

        try:
            message = self.client.messages.create(
                model=settings.anthropic_vision_model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # First content block: the image
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            # Second content block: the instruction
                            {
                                "type": "text",
                                "text": self._build_extraction_prompt(url),
                            },
                        ],
                    }
                ],
            )

            extracted = message.content[0].text
            logger.info(
                f"Extraction successful: {len(extracted)} chars extracted from {url}"
            )
            return extracted

        except Exception as e:
            logger.error(f"Vision extraction failed for {url}: {e}")
            raise

    def _build_extraction_prompt(self, url: str) -> str:
        """
        The prompt we send to Claude telling it how to extract content.
        
        A good prompt = better extraction quality.
        """
        return f"""You are a precise content extraction system. 
        
This is a screenshot of a webpage from: {url}

Your task is to extract ALL readable content from this image with perfect fidelity.

Instructions:
1. Extract ALL text you can see, maintaining the logical reading order
2. Format headings with # (H1), ## (H2), ### (H3) markers
3. Keep paragraphs separated by blank lines
4. Convert any tables to a readable text format (use | for columns)
5. Keep bullet points and numbered lists intact
6. DO NOT include: navigation menus, cookie banners, ads, footers with boilerplate
7. DO NOT add commentary or descriptions - only extract what is actually there
8. If you see a CAPTCHA or verification page, respond only with: CAPTCHA_DETECTED

Return only the extracted content, no preamble."""

    async def extract_from_text_with_structure(
        self, raw_text: str, url: str
    ) -> str:
        """
        Use Claude to clean and structure text that was extracted by HTML/DOM methods.
        
        This is optional - called when we want to improve HTML-extracted text.
        """
        try:
            message = self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Clean and structure the following raw text extracted from a webpage ({url}).

Remove: navigation items, cookie notices, repetitive boilerplate, social media share buttons.
Keep: all actual article/page content, headings, lists, tables.
Format: Use markdown for headings (#, ##) and preserve lists.

Raw text:
---
{raw_text[:8000]}
---

Return only the cleaned content.""",
                    }
                ],
            )
            return message.content[0].text
        except Exception as e:
            logger.warning(f"Text cleanup failed, returning raw: {e}")
            return raw_text
