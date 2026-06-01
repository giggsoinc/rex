"""Text extraction, hashing, and timestamp helpers for the scanner.

Extracted from scanner.py to keep modules under the line limit.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path

import structlog

from rex.models.schemas import MediaType

logger = structlog.get_logger()


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
