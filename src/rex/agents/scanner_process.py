"""Per-file processing mixin for LocalScanner.

Extracted from scanner.py to keep modules under the line limit. The mixin
expects the host class to provide: self.jobs, self.vectors, self.vision,
self.model, self.settings.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from rex.agents.scanner_extract import (
    extract_text,
    file_timestamps,
    sha256_of_file,
)
from rex.agents.scanner_meta import detect_media_type, detect_mime
from rex.models.schemas import FileContext, FileRecord, MediaType

logger = structlog.get_logger()


class ScannerProcessMixin:
    """Holds the heavy per-file processing logic for LocalScanner."""

    async def _process_one(self, file_path: str, job_id: str) -> FileContext | None:
        """Process a single file end to end."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return None

        ext = path.suffix.lower()
        media_type = detect_media_type(ext)
        mime = detect_mime(ext)

        # Hash first — gates idempotency
        sha = await sha256_of_file(path)

        # Idempotency: skip if same hash already scanned this job
        existing = await self.jobs.get_file_by_hash(job_id, sha)
        if existing is not None:
            # Already scanned — load embedding from vector store if available
            similar = await self._find_similar(existing.id, top_k=3)
            categories = await self._collect_existing_categories(job_id)
            return FileContext(
                file_record=existing,
                embedding=None,
                similar_files=similar,
                existing_categories=categories,
            )

        # Timestamps
        created, modified = file_timestamps(path)

        # Text extraction
        text = await extract_text(path, media_type, self.settings.max_text_chars)

        # Image description via vision (only if image AND key configured)
        image_desc = None
        exif: dict | None = None
        if media_type == MediaType.IMAGE:
            try:
                from rex.config import VisionProvider
                if self.settings.vision_provider != VisionProvider.NONE and self.settings.gemini_api_key:
                    image_desc = await self.vision.describe_image(path)
                else:
                    logger.info("vision_skipped_no_key", path=str(path))
            except Exception as e:
                logger.warning("vision_failed", path=str(path), error=str(e))
            exif = self._read_exif(path)

        # Build FileRecord
        record = FileRecord(
            job_id=job_id,
            original_path=str(path.resolve()),
            filename=path.name,
            extension=ext,
            mime_type=mime,
            media_type=media_type,
            size_bytes=path.stat().st_size,
            sha256_hash=sha,
            created_at=created,
            modified_at=modified,
            extracted_text=text[: self.settings.max_text_chars] if text else None,
            text_char_count=len(text),
            image_description=image_desc,
            exif_data=exif,
        )
        await self.jobs.save_file(record)

        # Embed (use text if available, fallback to filename+description for images)
        # IMPORTANT: truncate aggressively — all-minilm has a 256-token context window
        from rex.utils.skip_rules import truncate_for_embedding
        embed_input_raw = text or image_desc or path.stem.replace("_", " ").replace("-", " ")
        embed_input = truncate_for_embedding(embed_input_raw, max_chars=500)
        embedding: list[float] = []
        if embed_input.strip():
            try:
                embedding = await self.model.embed(embed_input)
            except Exception as e:
                logger.warning("embed_failed", path=str(path), error=str(e)[:200])

        # Store vector
        if embedding:
            try:
                await self.vectors.upsert(
                    file_id=record.id,
                    embedding=embedding,
                    metadata={
                        "job_id": job_id,
                        "filename": record.filename,
                        "ext": ext,
                        "media_type": media_type.value,
                        "sha": sha,
                    },
                )
            except Exception as e:
                logger.warning("vector_upsert_failed", path=str(path), error=str(e))

        # Find neighbors for router
        similar = await self._find_similar(record.id, query_vector=embedding, top_k=3)

        # Existing categories so far (for router prompt)
        categories = await self._collect_existing_categories(job_id)

        return FileContext(
            file_record=record,
            embedding=embedding,
            similar_files=similar,
            existing_categories=categories,
        )
