"""MIME / media-type detection helpers for the scanner.

Pure mapping logic extracted from scanner.py to keep modules small.
"""

from __future__ import annotations

from rex.models.schemas import MediaType


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
