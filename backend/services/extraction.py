"""
services/extraction.py - AI Vision Extraction

When a webpage cannot be read as structured text (because it uses a complex
canvas layout, heavy CSS-positioned elements, or the rendered HTML produces
very little usable text), the ingest pipeline takes a full-page screenshot
and sends it to a vision-language model (VLM).

The VLM receives the screenshot as a base64-encoded PNG and returns
clean Markdown with:
- Headings and document structure (# / ## / ###)
- Paragraphs of extracted text
- Tables converted to Markdown pipe format (| col | col |)
- Bullet and numbered lists

The VLM endpoint is an OpenAI-compatible API (CERIT-SC AIaaS) configured via
VLM_BASE_URL and VLM_API_KEY environment variables. The model name is
set via VLM_MODEL (e.g. "Qwen2.5-VL-7B-Instruct").

A secondary method (extract_from_text_with_structure) uses the text LLM
(not the vision model) to clean up HTML-extracted text by removing boilerplate.
"""

import base64
import logging

from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ExtractionService:
    """
    Sends screenshots to a vision-language model and returns extracted Markdown.

    One instance is created per IngestService (one per ingest job).
    The underlying HTTP client is recreated each time — connection pooling is
    not needed at our request rate and it avoids stale connections.
    """

    def __init__(self):
        # AsyncOpenAI wraps the OpenAI SDK's async client.
        # Works with any OpenAI-compatible endpoint, not just OpenAI itself.
        self.client = AsyncOpenAI(
            base_url=settings.vlm_base_url,
            api_key=settings.vlm_api_key,
        )

    async def extract_from_screenshot(
        self,
        screenshot_bytes: bytes,
        url: str,
    ) -> str:
        """
        Send a full-page PNG screenshot to the VLM and get back Markdown text.

        The image is base64-encoded and sent as a data: URL inside the message
        content (the standard multimodal message format for OpenAI-compatible APIs).
        The VLM "sees" the screenshot as a human would and extracts all readable
        content in a structured format.

        A special CAPTCHA_DETECTED string in the response is checked upstream
        by the ingest pipeline — if the screenshot shows a CAPTCHA page, this
        signals the pipeline to raise a CaptchaDetectedError instead of saving
        garbage text as the document content.

        Args:
            screenshot_bytes: Raw PNG bytes of the full-page screenshot.
            url: The URL that was screenshotted (included in the prompt for context).

        Returns:
            Markdown string containing the extracted page content.

        Raises:
            Exception: If the VLM API call fails (network error, auth error, etc.).
        """
        # Encode the PNG as base64 so it can be embedded in a JSON API request
        image_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

        logger.info(f"Sending screenshot to {settings.vlm_model} for URL: {url}")

        try:
            response = await self.client.chat.completions.create(
                model=settings.vlm_model,
                max_tokens=4096,  # enough for a full page of extracted text
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                # The image content part: embed PNG as a data: URL
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                },
                            },
                            {
                                # The text instruction part: tells the VLM what to do
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
        Use the text LLM to clean and reformat raw extracted text.

        HTML extraction often produces noisy text with navigation items, cookie
        notices, repeated footer text, and social media buttons mixed in with
        the actual article content. This method sends the raw text to the LLM
        and asks it to remove the noise and return only the real content in
        clean Markdown.

        This is an optional step and uses the text LLM (settings.query_model),
        not the vision model. It's slower than pure text extraction but produces
        better quality output for complex pages.

        Args:
            raw_text: The noisy text extracted by BeautifulSoup or markdownify.
            url: The source URL (included in the prompt for context).

        Returns:
            Cleaned Markdown text, or the original raw_text if the LLM call fails.
        """
        try:
            response = await self.client.chat.completions.create(
                model=settings.query_model,  # text model, not vision model
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
            # Cleaning is best-effort — if it fails, return the original text
            logger.warning(f"Text cleanup failed, returning raw: {e}")
            return raw_text

    def _build_extraction_prompt(self, url: str) -> str:
        """
        Build the system instruction sent to the VLM alongside the screenshot.

        The prompt is carefully structured to:
        1. Instruct the model to extract ALL visible text in reading order.
        2. Use consistent Markdown formatting for headings, tables, lists.
        3. Omit boilerplate (nav, ads, cookie banners).
        4. Return a special sentinel ("CAPTCHA_DETECTED") if the screenshot
           shows a bot-protection challenge instead of real content.
           The ingest pipeline checks for this string and raises CaptchaDetectedError.

        Args:
            url: The URL of the page — included so the model has context about
                 what type of content to expect.

        Returns:
            The extraction instruction string.
        """
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
