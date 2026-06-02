"""Pydantic models for the Planner output."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BatchType(str, Enum):
    """Coarse categorization for batching."""

    TEXT_SMALL = "text_small"        # markdown, txt, json, < 1MB
    TEXT_LARGE = "text_large"        # text files > 1MB
    PDF = "pdf"
    OFFICE = "office"                # docx, pptx, xlsx
    HTML = "html"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    CODE = "code"
    ARCHIVE = "archive"
    BINARY = "binary"
    OTHER = "other"


class BatchStatus(str, Enum):
    """Lifecycle states for a batch."""

    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DEAD = "dead"  # exceeded retries


class SkippedFile(BaseModel):
    """A file the Planner decided not to include."""

    path: str
    reason: str
    size_bytes: int = 0


class BatchFile(BaseModel):
    """One file inside a batch (lightweight metadata only)."""

    path: str
    name: str
    size_bytes: int
    extension: str


class Batch(BaseModel):
    """A unit of work for a Rex worker."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    type: BatchType
    files: list[BatchFile]
    estimated_seconds: int = 0
    estimated_tokens: int = 0
    status: BatchStatus = BatchStatus.PENDING
    assigned_worker: Optional[str] = None
    attempt: int = 0
    last_heartbeat: Optional[datetime] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)


class ScanPlan(BaseModel):
    """The planner's output — what will be scanned, in what batches."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    project_name: str
    source_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    total_files: int = 0
    total_bytes: int = 0
    skipped: list[SkippedFile] = Field(default_factory=list)
    batches: list[Batch] = Field(default_factory=list)

    estimated_seconds: int = 0
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0

    # Bucket counts for fast UI display
    files_by_type: dict[str, int] = Field(default_factory=dict)

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    def summary(self) -> dict:
        """Compact summary dict for UI / MCP."""
        return {
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "skipped": len(self.skipped),
            "batches": len(self.batches),
            "files_by_type": self.files_by_type,
            "estimated_seconds": self.estimated_seconds,
        }
