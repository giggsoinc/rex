"""Scanner agent — walks a folder, extracts text, fingerprints, embeds.

Streams FileContext objects downstream. Never buffers the whole directory.
Errors per-file are logged and skipped; the agent never dies mid-scan.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

import structlog

from rex.config import Settings, get_settings
from rex.ml.provider import ModelProvider
from rex.ml.vision import VisionEngine
from rex.models.schemas import FileContext, FileRecord, MediaType, SimilarFile
from rex.orchestrator.state import JobStore
from rex.plugins.local_fs import LocalFSPlugin
from rex.vectorstore import VectorStore

logger = structlog.get_logger()


# --- MIME / media type detection ---

TEXT_EXTS = {".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"}
DOC_EXTS = {".pdf", ".docx", ".doc", ".odt", ".rtf"}
SLIDE_EXTS = {".pptx", ".ppt", ".odp"}
SHEET_EXTS = {".xlsx", ".xls", ".ods"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar"}
CODE_EXTS = {".py", ".js", ".ts", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".rb", ".php", ".swift"}

MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".html": "text/html",
    ".csv": "text/csv",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".zip": "application/zip",
}


def detect_media_type(ext: str) -> MediaType:
    """Map extension to broad MediaType."""
    ext = ext.lower()
    if ext in TEXT_EXTS or ext in DOC_EXTS or ext in SLIDE_EXTS or ext in SHEET_EXTS or ext in CODE_EXTS:
        return MediaType.TEXT
    if ext in IMAGE_EXTS:
        return MediaType.IMAGE
    if ext in VIDEO_EXTS:
        return MediaType.VIDEO
    if ext in AUDIO_EXTS:
        return MediaType.AUDIO
    if ext in ARCHIVE_EXTS:
        return MediaType.ARCHIVE
    return MediaType.BINARY


def detect_mime(ext: str) -> str:
    """Guess MIME from extension."""
    return MIME_MAP.get(ext.lower(), "application/octet-stream")


# --- Text extraction ---

async def extract_text(path: Path, media_type: MediaType, max_chars: int) -> str:
    """Extract textual content from a file. Returns first max_chars only.

    Uses Unstructured.io for binary docs (PDF, DOCX, PPTX).
    Plain text files: direct read.
    Images/video: empty (vision handled separately).
    """
    try:
        if media_type == MediaType.TEXT:
            ext = path.suffix.lower()
            if ext in {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls"}:
                return await _unstructured_extract(path, max_chars)
            # Plain text/markdown/json/etc.
            def _read():
                try:
                    return path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    return ""
            text = await asyncio.to_thread(_read)
            return text[:max_chars]

        if media_type in {MediaType.IMAGE, MediaType.VIDEO, MediaType.AUDIO, MediaType.ARCHIVE, MediaType.BINARY}:
            return ""

    except Exception as e:
        logger.warning("text_extraction_failed", path=str(path), error=str(e))
        return ""

    return ""


async def _unstructured_extract(path: Path, max_chars: int) -> str:
    """Use Unstructured.io for binary docs. Falls back gracefully if missing."""
    def _do_extract():
        try:
            from unstructured.partition.auto import partition
            elements = partition(filename=str(path))
            text = "\n".join(str(el) for el in elements)
            return text
        except ImportError:
            logger.warning("unstructured_not_installed", path=str(path))
            # Last-resort: try to grep readable strings from bytes for PDFs
            try:
                raw = path.read_bytes()
                # Crude: extract printable ASCII runs of length >= 4
                import re
                strings = re.findall(rb"[\x20-\x7e]{4,}", raw)
                return b"\n".join(strings[:200]).decode("ascii", errors="ignore")
            except Exception:
                return ""
        except Exception as e:
            logger.warning("unstructured_extract_failed", path=str(path), error=str(e))
            return ""

    text = await asyncio.to_thread(_do_extract)
    return text[:max_chars] if text else ""


# --- Hash + metadata ---

async def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 in 64KB chunks. Off-thread to avoid blocking."""
    def _hash():
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    return await asyncio.to_thread(_hash)


def file_timestamps(path: Path) -> tuple[datetime | None, datetime | None]:
    """Get creation + modification times."""
    try:
        stat = path.stat()
        created = datetime.fromtimestamp(stat.st_ctime)
        modified = datetime.fromtimestamp(stat.st_mtime)
        return created, modified
    except Exception:
        return None, None


# --- Scanner Agent ---

class LocalScanner:
    """Scanner agent implementation for local filesystem.

    Walks via LocalFSPlugin. Hashes, extracts, embeds, stores.
    Yields FileContext for downstream stages.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        vision_engine: VisionEngine,
        vector_store: VectorStore,
        job_store: JobStore,
        settings: Settings | None = None,
    ) -> None:
        self.model = model_provider
        self.vision = vision_engine
        self.vectors = vector_store
        self.jobs = job_store
        self.settings = settings or get_settings()
        self.fs = LocalFSPlugin()

    async def estimate_count(self, source_path: str) -> int:
        """Quick file count for progress reporting."""
        count = 0
        async for _ in self.fs.walk(source_path):
            count += 1
        return count

    async def scan(self, source_path: str, job_id: str) -> AsyncIterator[FileContext]:
        """Walk source_path, yield FileContext per file."""
        async for entry in self.fs.walk(source_path):
            try:
                ctx = await self._process_one(entry.path, job_id)
                if ctx is not None:
                    yield ctx
            except Exception as e:
                logger.error("scanner_file_failed", path=entry.path, error=str(e))
                # Continue — never let one file kill the scan

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
        embed_input = truncate_for_embedding(embed_input_raw, max_chars=1000)
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

    async def _find_similar(
        self,
        exclude_file_id: str,
        query_vector: list[float] | None = None,
        top_k: int = 3,
    ) -> list[SimilarFile]:
        """Top-k vector neighbors, excluding self."""
        if not query_vector:
            return []
        try:
            matches = await self.vectors.search(query_vector, top_k=top_k + 1)
        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            return []
        out = []
        for m in matches:
            if m.file_id == exclude_file_id:
                continue
            out.append(
                SimilarFile(
                    file_id=m.file_id,
                    filename=m.metadata.get("filename", ""),
                    similarity_score=m.similarity_score,
                )
            )
            if len(out) >= top_k:
                break
        return out

    async def _collect_existing_categories(self, job_id: str) -> list[str]:
        """Distinct categories assigned so far this job."""
        decisions = await self.jobs.list_decisions(job_id)
        cats = {d.category for d in decisions.values() if d.category}
        return sorted(cats)

    def _read_exif(self, path: Path) -> dict | None:
        """Best-effort EXIF read using Pillow."""
        try:
            from PIL import Image
            img = Image.open(path)
            exif = getattr(img, "_getexif", lambda: None)()
            if not exif:
                return None
            # Return safe subset
            return {str(k): str(v)[:200] for k, v in exif.items()}
        except Exception:
            return None
