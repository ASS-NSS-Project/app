"""
services/extraction_service.py - AI Vision Extraction

When a webpage can't be read as text, we take a screenshot and send it
to a local vision-language model via Ollama (qwen3-vl).

The model extracts:
- Headings and structure
- Paragraphs of text
- Tables (converted to text)
- Lists

Uses Ollama's OpenAI-compatible API with image_url content type.
"""

import base64
import logging

from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ExtractionService:
    """
    Uses a local vision-language model (via Ollama) to extract
    structured text from screenshots.
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
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

        logger.info(f"Sending screenshot to {settings.ollama_vision_model} for URL: {url}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.ollama_vision_model,
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
                model=settings.ollama_model,
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
