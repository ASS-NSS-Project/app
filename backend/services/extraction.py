"""
services/extraction_service.py - AI Vision Extraction

When a webpage can't be read as text, we take a screenshot and send it
to a vision-language model via the e-INFRA AIaaS OpenAI-compatible API.

The model extracts:
- Headings and structure
- Paragraphs of text
- Tables (converted to text)
- Lists
"""

import base64
import logging

from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ExtractionService:
    """
    Uses a vision-language model (e-INFRA AIaaS) to extract structured text from screenshots.
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.aiaas_base_url,
            api_key=settings.aiaas_api_key,
        )

    async def extract_from_screenshot(
        self,
        screenshot_bytes: bytes,
        url: str,
    ) -> str:
        """
        Send a screenshot to the vision model and get back structured text.
        """
        image_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

        logger.info(f"Sending screenshot to {settings.aiaas_vlm_model} for URL: {url}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.aiaas_vlm_model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": self._build_extraction_prompt(url),
                            },
                        ],
                    }
                ],
            )

            extracted = response.choices[0].message.content
            logger.info(f"Extraction successful: {len(extracted)} chars from {url}")
            return extracted

        except Exception as e:
            logger.error(f"Vision extraction failed for {url}: {e}")
            raise

    async def extract_from_text_with_structure(self, raw_text: str, url: str) -> str:
        """
        Use the text LLM to clean and structure text extracted by HTML/DOM methods.
        """
        try:
            response = await self.client.chat.completions.create(
                model=settings.aiaas_llm_model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Clean and structure the following raw text extracted from a webpage ({url}).\n\n"
                            f"Remove: navigation items, cookie notices, repetitive boilerplate, social media share buttons.\n"
                            f"Keep: all actual article/page content, headings, lists, tables.\n"
                            f"Format: Use markdown for headings (#, ##) and preserve lists.\n\n"
                            f"Raw text:\n---\n{raw_text[:8000]}\n---\n\nReturn only the cleaned content."
                        ),
                    }
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Text cleanup failed, returning raw: {e}")
            return raw_text

    def _build_extraction_prompt(self, url: str) -> str:
        return f"""You are a precise content extraction system.

This is a screenshot of a webpage from: {url}

Extract ALL readable content and format it as clean Markdown.

Instructions:
1. Extract ALL text, maintaining logical reading order
2. Use # / ## / ### for headings (ATX style)
3. Separate paragraphs with blank lines
4. Convert tables to Markdown table syntax (| col | col |)
5. Preserve bullet points (- item) and numbered lists (1. item)
6. OMIT: navigation menus, cookie banners, ads, repetitive footers
7. DO NOT add commentary — only extract what is on the page
8. If you see a CAPTCHA or verification page, respond only with: CAPTCHA_DETECTED

Return only the extracted Markdown content, no preamble."""
