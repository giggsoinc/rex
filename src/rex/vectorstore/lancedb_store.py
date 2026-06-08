"""LanceDB vector store — embedded, zero-infra, Parquet on disk.

Default for local/ideation deployment.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from rex.vectorstore.base import VectorMatch, VectorStore
from rex.vectorstore.lancedb_helpers import (
    build_schema,
    merge_rows,
    rows_to_matches,
    run_search,
)
from rex.vectorstore.path_guard import validate_writable_path

logger = structlog.get_logger()


class LanceDBStore(VectorStore):
    """Embedded vector store using LanceDB (Parquet on disk).

    Zero infrastructure — just a folder. Perfect for laptop / ideation.
    """

    def __init__(self, db_path: str, table_name: str = "rex_vectors", dim: int = 384) -> None:
        """Initialize LanceDB store.

        Args:
            db_path: Local filesystem path for LanceDB data.
            table_name: Name of the vector table.
            dim: Embedding dimension (default 384 for all-minilm).
        """
        self.db_path = validate_writable_path(db_path, field="REX_VECTOR_PATH")
        self.table_name = table_name
        self.dim = dim
        self._db: Any = None
        self._table: Any = None

    async def initialize(self) -> None:
        """Create LanceDB database and table if not present."""
        import lancedb

        self.db_path.mkdir(parents=True, exist_ok=True)
        self._db = await asyncio.to_thread(lancedb.connect, str(self.db_path))

        existing_tables = await asyncio.to_thread(lambda: list(self._db.table_names()))
        if self.table_name in existing_tables:
            self._table = await asyncio.to_thread(self._db.open_table, self.table_name)
            logger.info("lancedb_table_opened", path=str(self.db_path), table=self.table_name)
        else:
            schema = build_schema(self.dim)
            self._table = await asyncio.to_thread(self._db.create_table, self.table_name, schema=schema)
            logger.info("lancedb_table_created", path=str(self.db_path), table=self.table_name, dim=self.dim)

    async def upsert(self, file_id: str, embedding: list[float], metadata: dict) -> None:
        """Upsert one vector. LanceDB doesn't have native upsert — delete then add."""
        if self._table is None:
            await self.initialize()

        def _do_upsert():
            try:
                self._table.delete(f"file_id = '{file_id}'")
            except Exception:
                pass  # No-op if file_id not present
            self._table.add(
                [
                    {
                        "file_id": file_id,
                        "vector": embedding,
                        "metadata_json": json.dumps(metadata),
                    }
                ]
            )

        await asyncio.to_thread(_do_upsert)

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[VectorMatch]:
        """Top-k cosine similarity search."""
        if self._table is None:
            await self.initialize()

        results = await asyncio.to_thread(run_search, self._table, query_vector, top_k, filters)
        return rows_to_matches(results)

    async def delete(self, file_id: str) -> None:
        """Delete a vector by file_id."""
        if self._table is None:
            await self.initialize()
        await asyncio.to_thread(self._table.delete, f"file_id = '{file_id}'")

    async def count(self) -> int:
        """Return total vector count."""
        if self._table is None:
            await self.initialize()
        return await asyncio.to_thread(lambda: self._table.count_rows())

    async def health_check(self) -> bool:
        """Verify LanceDB is operational."""
        try:
            await self.initialize()
            await self.count()
            return True
        except Exception as e:
            logger.error("lancedb_health_check_failed", error=str(e))
            return False

    async def close(self) -> None:
        """LanceDB is embedded — no connection to close."""
        self._db = None
        self._table = None

    async def merge_from(self, other_path: str) -> int:
        """Merge another LanceDB's vectors into this one. Returns rows merged.

        Used by Janitor after parallel workers finish to consolidate shards.
        """
        if self._table is None:
            await self.initialize()

        merged = await asyncio.to_thread(merge_rows, self._table, self.table_name, other_path)
        logger.info("lancedb_merged", from_path=other_path, rows=merged)
        return merged
