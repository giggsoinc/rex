"""SQLAlchemy async models — PostgreSQL + pgvector tables."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rex.config import get_settings


class Base(AsyncAttrs, DeclarativeBase):
    """SQLAlchemy async base class."""

    pass


class JobTable(Base):
    """Scan job tracking."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    scanned_files: Mapped[int] = mapped_column(Integer, default=0)
    classified_files: Mapped[int] = mapped_column(Integer, default=0)
    organized_files: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    categories_discovered: Mapped[dict] = mapped_column(JSONB, default=list)
    pre_organized: Mapped[bool] = mapped_column(Boolean, default=False)
    enhance_in_place: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    files: Mapped[list[FileTable]] = relationship(back_populates="job", cascade="all, delete-orphan")


class FileTable(Base):
    """File records — one row per scanned file."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_char_count: Mapped[int] = mapped_column(Integer, default=0)
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    exif_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Phase II: graph readiness
    entity_type: Mapped[str] = mapped_column(String(50), default="File")
    relation_hints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    job: Mapped[JobTable] = relationship(back_populates="files")
    embedding: Mapped[EmbeddingTable | None] = relationship(back_populates="file", uselist=False)
    decision: Mapped[DecisionTable | None] = relationship(back_populates="file", uselist=False)


class EmbeddingTable(Base):
    """Vector embeddings — pgvector storage for similarity search."""

    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"), unique=True, nullable=False)
    embedding = mapped_column(Vector(384), nullable=False)  # all-minilm = 384 dimensions
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    file: Mapped[FileTable] = relationship(back_populates="embedding")

    __table_args__ = (
        Index("ix_embeddings_vector", embedding, postgresql_using="hnsw", postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class DecisionTable(Base):
    """LLM Router decisions — what to do with each file."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"), unique=True, nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tags: Mapped[dict] = mapped_column(JSONB, default=list)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dedup_status: Mapped[str] = mapped_column(String(20), default="unique")
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Phase II: graph readiness
    entity_type: Mapped[str] = mapped_column(String(50), default="File")
    relation_hints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    file: Mapped[FileTable] = relationship(back_populates="decision")


# --- Engine + Session Factory ---

def get_engine(db_url: str | None = None):
    """Create async SQLAlchemy engine."""
    url = db_url or get_settings().db_url
    return create_async_engine(url, echo=False, pool_size=10, max_overflow=20)


def get_session_factory(engine=None):
    """Create async session factory."""
    if engine is None:
        engine = get_engine()
    return async_sessionmaker(engine, expire_on_commit=False)
