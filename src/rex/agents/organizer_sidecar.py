"""Per-file metadata sidecar builder for the organizer.

Extracted from organizer_catalog.py to keep modules under the line limit.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rex.models.schemas import FileDecision, FileRecord


def build_sidecar(file_record: FileRecord, decision: FileDecision, dest_path: Path) -> dict:
    """Construct the per-file metadata sidecar dict."""
    return {
        "file_id": file_record.id,
        "job_id": file_record.job_id,
        "original_path": file_record.original_path,
        "new_path": str(dest_path),
        "filename": file_record.filename,
        "sha256": file_record.sha256_hash,
        "size_bytes": file_record.size_bytes,
        "mime_type": file_record.mime_type,
        "media_type": file_record.media_type.value,
        "modified_at": file_record.modified_at.isoformat() if file_record.modified_at else None,
        "category": decision.category,
        "tags": decision.tags,
        "relevance": decision.relevance,
        "action": decision.action.value,
        "dedup_status": decision.dedup_status.value,
        "duplicate_of": decision.duplicate_of,
        "reasoning": decision.reasoning,
        "extracted_text_preview": (file_record.extracted_text or "")[:500],
        "image_description": file_record.image_description,
        "entity_type": decision.entity_type,
        "relation_hints": decision.relation_hints,
        "organized_at": datetime.utcnow().isoformat() + "Z",
    }
