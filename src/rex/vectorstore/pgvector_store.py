"""PostgreSQL + pgvector store — enterprise self-hosted backend.

Stub for now. Full implementation when enterprise customer needs it.
"""

from __future__ import annotations

from rex.vectorstore.base import VectorMatch, VectorStore


class PgVectorStore(VectorStore):
    """PostgreSQL + pgvector backend. Enterprise self-hosted option."""

    def __init__(
        self,
        db_url: str,
        table_name: str = "rex_vectors",
        dim: int = 384,
    ) -> None:
        self.db_url = db_url
        self.table_name = table_name
        self.dim = dim

    async def initialize(self) -> None:
        raise NotImplementedError("PgVectorStore is a Phase II enterprise backend. Use LanceDB for local.")

    async def upsert(self, file_id: str, embedding: list[float], metadata: dict) -> None:
        raise NotImplementedError("PgVectorStore not yet implemented.")

    async def search(self, query_vector: list[float], top_k: int = 5, filters: dict | None = None) -> list[VectorMatch]:
        raise NotImplementedError("PgVectorStore not yet implemented.")

    async def delete(self, file_id: str) -> None:
        raise NotImplementedError("PgVectorStore not yet implemented.")

    async def count(self) -> int:
        raise NotImplementedError("PgVectorStore not yet implemented.")

    async def health_check(self) -> bool:
        return False

    async def close(self) -> None:
        pass
