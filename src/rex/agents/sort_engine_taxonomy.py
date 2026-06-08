"""Type taxonomy + path safety helpers for SortEngine.

12-bucket file-type taxonomy (locked design). Lives in its own module so the
main sort_engine.py stays under the 150-line guard.
"""

from __future__ import annotations

import re

__all__ = [
    "EXTENSION_BUCKETS",
    "REVIEW_DIR",
    "UNSORTED_DIR",
    "TRASH_DIR",
    "ARCHIVE_DIR",
    "STALE_DIR",
    "extension_to_bucket",
    "safe_segment",
]

# 12-bucket type taxonomy — extension → bucket name
EXTENSION_BUCKETS: dict[str, str] = {
    # Docs (Word-class)
    ".doc": "Docs", ".docx": "Docs", ".rtf": "Docs", ".odt": "Docs", ".pages": "Docs",
    # Notes (plain text + markup)
    ".md": "Notes", ".markdown": "Notes", ".txt": "Notes", ".rst": "Notes", ".org": "Notes",
    # PDFs (own bucket — high volume)
    ".pdf": "PDFs",
    # Spreadsheets
    ".xls": "Spreadsheets", ".xlsx": "Spreadsheets", ".csv": "Spreadsheets",
    ".tsv": "Spreadsheets", ".ods": "Spreadsheets", ".numbers": "Spreadsheets",
    # Presentations
    ".ppt": "Presentations", ".pptx": "Presentations", ".odp": "Presentations", ".key": "Presentations",
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".webp": "Images", ".bmp": "Images", ".heic": "Images", ".svg": "Images", ".tiff": "Images",
    # Videos
    ".mp4": "Videos", ".mov": "Videos", ".avi": "Videos", ".mkv": "Videos",
    ".webm": "Videos", ".m4v": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".m4a": "Audio",
    ".ogg": "Audio", ".aac": "Audio",
    # Archives
    ".zip": "Archives", ".tar": "Archives", ".gz": "Archives", ".7z": "Archives", ".rar": "Archives",
    # Code
    ".py": "Code", ".js": "Code", ".ts": "Code", ".go": "Code", ".java": "Code",
    ".cpp": "Code", ".rb": "Code", ".rs": "Code", ".sh": "Code", ".tsx": "Code", ".jsx": "Code",
    # Data (structured)
    ".json": "Data", ".xml": "Data", ".yaml": "Data", ".yml": "Data",
    ".parquet": "Data", ".sql": "Data", ".db": "Data",
}

# Special destination folders
REVIEW_DIR = "_Review"
UNSORTED_DIR = "_Unsorted"
TRASH_DIR = "_Trash"
ARCHIVE_DIR = "_Archive"
STALE_DIR = "_Stale"  # older versions superseded by a higher V<N> in the same group

_SAFE_PATH_RE = re.compile(r"[^a-zA-Z0-9._\-]")


def extension_to_bucket(extension: str) -> str:
    """Map a file extension into one of the 12 type buckets — default 'Other'."""
    return EXTENSION_BUCKETS.get(extension.lower(), "Other")


def safe_segment(s: str) -> str:
    """Sanitize a path segment for cross-platform safety."""
    s = s.strip().strip("/").replace("\\", "_")
    s = _SAFE_PATH_RE.sub("_", s)
    return s or "Unknown"
