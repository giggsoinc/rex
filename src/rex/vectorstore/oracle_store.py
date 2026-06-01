"""Oracle 26AI Vector Store — enterprise managed backend.

Stub for now. Implemented when enterprise customer onboards Oracle.
"""

from __future__ import annotations

from rex.vectorstore.base import VectorMatch, VectorStore


class OracleVectorStore(VectorStore):
    """Oracle 26AI Vector Store backend. Enterprise managed option."""

    def __init__(
        self,
        host: str,
        port: int,
        service: str,
        user: str,
        password: str,
        table_name: str = "REX_VECTORS",
        dim: int = 384,
    ) -> None:
        self.host = host
        self.port = port
        self.service = service
        self.user = user
        self.password = password
        self.table_name = table_name
        self.dim = dim

    async def initialize(self) -> None:
        raise NotImplementedError("OracleVectorStore is a Phase II enterprise backend. Use LanceDB for local.")

    async def upsert(self, file_id: str, embedding: list[float], metadata: dict) -> None:
        raise NotImplementedError("OracleVectorStore not yet implemented.")

    async def search(self, query_vector: list[float], top_k: int = 5, filters: dict | None = None) -> list[VectorMatch]:
        raise NotImplementedError("OracleVectorStore not yet implemented.")

    async def delete(self, file_id: str) -> None:
        raise NotImplementedError("OracleVectorStore not yet implemented.")

    async def count(self) -> int:
        raise NotImplementedError("OracleVectorStore not yet implemented.")

    async def health_check(self) -> bool:
        return False

    async def close(self) -> None:
        pass
