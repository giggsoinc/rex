"""VectorStore abstract interface — every backend implements this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VectorMatch:
    """A neighbor returned from vector search."""

    file_id: str
    similarity_score: float       # 0.0 to 1.0 (cosine similarity)
    metadata: dict = field(default_factory=dict)


class VectorStore(ABC):
    """Abstract vector store — backends: LanceDB, pgvector, Oracle 26AI, ChromaDB.

    Same code for ideation laptop and enterprise production.
    Onboarding picks the backend; agents never know which one is active.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Set up storage: create tables/collections/files as needed.

        Called once at startup. Idempotent.
        """
        ...

    @abstractmethod
    async def upsert(
        self,
        file_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Insert or update an embedding with associated metadata.

        Args:
            file_id: Unique file identifier.
            embedding: Vector representation (e.g., 384d for all-minilm).
            metadata: Searchable metadata (filename, category, tags, etc.).
        """
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[VectorMatch]:
        """Find top-k most similar vectors.

        Args:
            query_vector: Query embedding.
            top_k: How many neighbors to return.
            filters: Optional metadata filters (e.g., {"category": "Documents"}).

        Returns:
            List of VectorMatch ordered by similarity (highest first).
        """
        ...

    @abstractmethod
    async def delete(self, file_id: str) -> None:
        """Remove an embedding by file_id."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return total number of embeddings stored."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if backend is reachable and operational."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources (connections, file handles)."""
        ...
