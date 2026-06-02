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

# Per-format dispatch — each entry is a sync extractor(path, max_chars) -> str.
_EXTRACTORS: dict[str, str] = {
    ".pdf": "extract_pdf",
    ".docx": "extract_docx",
    ".pptx": "extract_pptx",
    ".xlsx": "extract_xlsx",
    ".doc": "extract_legacy",
    ".ppt": "extract_legacy",
    ".xls": "extract_legacy",
}


async def extract_text(path: Path, media_type: MediaType, max_chars: int) -> str:
    """Extract textual content from a file. Returns first max_chars only.

    Routes each format to a dedicated pure-Python extractor (no LibreOffice):
      pdf->pdfplumber/pypdf, docx->python-docx, pptx->python-pptx, xlsx->openpyxl.
    Legacy .doc/.ppt/.xls degrade to "" (classified by filename/metadata).
    Plain text: direct read. Images/video/audio/archive/binary: "".
    Never raises — one bad file must not kill the batch.
    """
    if media_type != MediaType.TEXT:
        return ""

    ext = path.suffix.lower()
    fn_name = _EXTRACTORS.get(ext)
    try:
        if fn_name is not None:
            from rex.agents import scanner_extractors as ex
            fn = getattr(ex, fn_name)
            text = await asyncio.to_thread(fn, path, max_chars)
            return text[:max_chars] if text else ""

        # Plain text/markdown/json/csv/etc.
        def _read() -> str:
            """Read the file as UTF-8 text, ignoring decode errors."""
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
        text = await asyncio.to_thread(_read)
        return text[:max_chars]
    except Exception as e:
        logger.warning("text_extraction_failed", path=str(path), error=str(e)[:120])
        return ""


# --- Hash + metadata ---

async def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 in 64KB chunks. Off-thread to avoid blocking."""
    def _hash():
        """Stream the file through SHA-256 in 64KB chunks."""
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
