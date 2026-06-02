"""Gemini Flash vision — image understanding, OCR, PDF embedded image analysis."""

from __future__ import annotations

from pathlib import Path

import structlog

from rex.config import Settings, VisionProvider, get_settings
from rex.ml.vision_helpers import GeminiVisionMixin

logger = structlog.get_logger()


class VisionEngine(GeminiVisionMixin):
    """Image understanding via Gemini Flash (or other vision providers)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    def _get_gemini_client(self):
        """Lazy init Gemini client. API key resolved via SecretProvider."""
        if self._client is None:
            from google import genai
            from rex.secrets import get_secret_provider
            import asyncio

            api_key = self.settings.gemini_api_key
            if not api_key:
                # Fallback to secret provider
                provider = get_secret_provider(self.settings)
                try:
                    api_key = asyncio.get_event_loop().run_until_complete(
                        provider.get("providers.gemini.api_key")
                    )
                except Exception:
                    api_key = ""
            self._client = genai.Client(api_key=api_key)
        return self._client

    async def describe_image(self, image_path: str | Path) -> str:
        """Get a natural language description of an image.

        Args:
            image_path: Path to image file.

        Returns:
            Description string from vision model.
        """
        if self.settings.vision_provider == VisionProvider.NONE:
            return ""

        if self.settings.vision_provider == VisionProvider.GEMINI:
            return await self._gemini_describe(image_path)
        else:
            raise ValueError(f"Unsupported vision provider: {self.settings.vision_provider}")

    async def extract_text_from_image(self, image_path: str | Path) -> str:
        """OCR — extract text from an image.

        Args:
            image_path: Path to image file.

        Returns:
            Extracted text content.
        """
        if self.settings.vision_provider == VisionProvider.NONE:
            return ""

        if self.settings.vision_provider == VisionProvider.GEMINI:
            return await self._gemini_ocr(image_path)
        else:
            raise ValueError(f"Unsupported vision provider: {self.settings.vision_provider}")

    async def describe_pdf_images(self, pdf_path: str | Path, image_bytes_list: list[bytes]) -> list[str]:
        """Describe images embedded in a PDF.

        Args:
            pdf_path: Path to source PDF (for context).
            image_bytes_list: List of image bytes extracted from PDF.

        Returns:
            List of descriptions, one per image.
        """
        descriptions = []
        for img_bytes in image_bytes_list:
            desc = await self._gemini_describe_bytes(img_bytes, context=f"Image from PDF: {pdf_path}")
            descriptions.append(desc)
        return descriptions

    async def health_check(self) -> bool:
        """Check if vision provider is available."""
        if self.settings.vision_provider == VisionProvider.NONE:
            return True
        try:
            client = self._get_gemini_client()
            # Simple test
            response = client.models.generate_content(
                model=self.settings.vision_model,
                contents="Respond with OK",
            )
            return bool(response.text)
        except Exception as e:
            logger.error("vision_health_check_failed", error=str(e))
            return False
