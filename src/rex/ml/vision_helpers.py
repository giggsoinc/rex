"""Gemini vision implementations + MIME helper — mixin for VisionEngine.

Split out of vision.py to satisfy the 150-line file limit. Relies on the host
class providing `_get_gemini_client()` and `settings`.
"""

from __future__ import annotations

import base64
from pathlib import Path

import structlog

logger = structlog.get_logger()


class GeminiVisionMixin:
    """Gemini Flash describe/OCR implementations. Host provides client + settings."""

    async def _gemini_describe(self, image_path: str | Path) -> str:
        """Describe an image using Gemini Flash."""
        try:
            client = self._get_gemini_client()
            image_path = Path(image_path)

            with open(image_path, "rb") as f:
                image_data = f.read()

            b64 = base64.b64encode(image_data).decode("utf-8")
            mime = _guess_image_mime(image_path)

            response = client.models.generate_content(
                model=self.settings.vision_model,
                contents=[
                    {
                        "parts": [
                            {"text": "Describe this image in detail. Include: what it shows, any text visible, "
                                     "whether it's a photo/screenshot/diagram/chart, and its likely purpose or context. "
                                     "Be concise but thorough."},
                            {"inline_data": {"mime_type": mime, "data": b64}},
                        ]
                    }
                ],
            )
            return response.text or ""
        except Exception as e:
            logger.error("gemini_describe_failed", path=str(image_path), error=str(e))
            return f"[Vision error: {e}]"

    async def _gemini_ocr(self, image_path: str | Path) -> str:
        """Extract text from image using Gemini Flash."""
        try:
            client = self._get_gemini_client()
            image_path = Path(image_path)

            with open(image_path, "rb") as f:
                image_data = f.read()

            b64 = base64.b64encode(image_data).decode("utf-8")
            mime = _guess_image_mime(image_path)

            response = client.models.generate_content(
                model=self.settings.vision_model,
                contents=[
                    {
                        "parts": [
                            {"text": "Extract ALL text visible in this image. Return only the text content, "
                                     "preserving layout where possible. If no text is visible, respond with: NO_TEXT"},
                            {"inline_data": {"mime_type": mime, "data": b64}},
                        ]
                    }
                ],
            )
            text = response.text or ""
            return "" if text.strip() == "NO_TEXT" else text
        except Exception as e:
            logger.error("gemini_ocr_failed", path=str(image_path), error=str(e))
            return ""

    async def _gemini_describe_bytes(self, image_bytes: bytes, context: str = "") -> str:
        """Describe image from raw bytes."""
        try:
            client = self._get_gemini_client()
            b64 = base64.b64encode(image_bytes).decode("utf-8")

            response = client.models.generate_content(
                model=self.settings.vision_model,
                contents=[
                    {
                        "parts": [
                            {"text": f"Describe this image. Context: {context}. "
                                     "What does it show? Any text? Type (photo/chart/diagram)? Purpose?"},
                            {"inline_data": {"mime_type": "image/png", "data": b64}},
                        ]
                    }
                ],
            )
            return response.text or ""
        except Exception as e:
            logger.error("gemini_describe_bytes_failed", error=str(e))
            return f"[Vision error: {e}]"


def _guess_image_mime(path: Path) -> str:
    """Guess MIME type from file extension."""
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".svg": "image/svg+xml",
    }
    return mime_map.get(path.suffix.lower(), "image/png")
