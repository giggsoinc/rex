"""Core data models — contracts between Scanner, Router, and Organizer."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Enums ---

class MediaType(str, Enum):
    """Broad media classification."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    BINARY = "binary"


class FileAction(str, Enum):
    """What the LLM router decides to do with a file."""

    KEEP = "keep"
    ARCHIVE = "archive"
    TRASH = "trash"


class DedupStatus(str, Enum):
    """Deduplication classification."""

    UNIQUE = "unique"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    RELATED = "related"


class JobStatus(str, Enum):
    """Pipeline job states."""

    PENDING = "pending"
    SCANNING = "scanning"
    ROUTING = "routing"
    ORGANIZING = "organizing"
    COMPLETE = "complete"
    FAILED = "failed"
    PAUSED = "paused"


# --- Scanner Output ---

class FileRecord(BaseModel):
    """Raw file fingerprint — output of the Scanner agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    original_path: str
    filename: str
    extension: str
    mime_type: str
    media_type: MediaType
    size_bytes: int
    sha256_hash: str
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    extracted_text: Optional[str] = None
    text_char_count: int = 0
    image_description: Optional[str] = None
    exif_data: Optional[dict] = None
    scanned_at: datetime = Field(default_factory=datetime.utcnow)

    # Phase II graph readiness
    entity_type: str = "File"
    relation_hints: Optional[dict] = None


class FileContext(BaseModel):
    """Enriched context sent to the LLM Router — file + embeddings + neighbors."""

    file_record: FileRecord
    embedding: Optional[list[float]] = None
    similar_files: list[SimilarFile] = Field(default_factory=list)
    existing_categories: list[str] = Field(default_factory=list)


class SimilarFile(BaseModel):
    """A neighbor file found via pgvector cosine similarity."""

    file_id: str
    filename: str
    category: Optional[str] = None
    similarity_score: float
    dedup_status: DedupStatus = DedupStatus.UNIQUE


# --- Router Output ---

class FileDecision(BaseModel):
    """LLM Router decision — what to do with this file. PydanticAI structured output."""

    category: str = Field(description="Category to organize into (e.g., 'Documents/Finance', 'Presentations/Q3')")
    tags: list[str] = Field(description="Descriptive tags for search and indexing")
    relevance: int = Field(ge=1, le=5, description="Relevance score: 1=junk, 5=critical")
    duplicate_of: Optional[str] = Field(default=None, description="File ID this is a duplicate of, or null")
    dedup_status: DedupStatus = DedupStatus.UNIQUE
    action: FileAction = Field(description="What to do: keep, archive, or trash")
    reasoning: str = Field(description="One sentence explaining the decision")

    # Phase II graph readiness
    entity_type: str = Field(default="File", description="Knowledge graph node type")
    relation_hints: Optional[dict] = Field(default=None, description="Discovered relationships for graph edges")


# --- Job ---

class ScanJob(BaseModel):
    """A scan job — tracks pipeline progress."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    source_path: str
    output_path: str
    status: JobStatus = JobStatus.PENDING
    total_files: int = 0
    scanned_files: int = 0
    classified_files: int = 0
    organized_files: int = 0
    duplicate_count: int = 0
    categories_discovered: list[str] = Field(default_factory=list)
    pre_organized: bool = False
    enhance_in_place: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# Fix forward reference
FileContext.model_rebuild()
