"""ChromaDB Vector Store — enterprise self-hosted backend.

Stub for now. Implemented when customer prefers Chroma.
"""

from __future__ import annotations

from rex.vectorstore.base import VectorMatch, VectorStore


class ChromaDBStore(VectorStore):
    """ChromaDB backend. Enterprise self-hosted option."""

    def __init__(
        self,
        host: str,
        port: int,
        collection_name: str = "rex_vectors",
        dim: int = 384,
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.dim = dim

    async def initialize(self) -> None:
        raise NotImplementedError("ChromaDBStore is a Phase II enterprise backend. Use LanceDB for local.")

    async def upsert(self, file_id: str, embedding: list[float], metadata: dict) -> None:
        raise NotImplementedError("ChromaDBStore not yet implemented.")

    async def search(self, query_vector: list[float], top_k: int = 5, filters: dict | None = None) -> list[VectorMatch]:
        raise NotImplementedError("ChromaDBStore not yet implemented.")

    async def delete(self, file_id: str) -> None:
        raise NotImplementedError("ChromaDBStore not yet implemented.")

    async def count(self) -> int:
        raise NotImplementedError("ChromaDBStore not yet implemented.")

    async def health_check(self) -> bool:
        return False

    async def close(self) -> None:
        pass
