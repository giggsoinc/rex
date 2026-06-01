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
        self.db_path = Path(db_path).expanduser().resolve()
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
            schema = self._build_schema()
            self._table = await asyncio.to_thread(self._db.create_table, self.table_name, schema=schema)
            logger.info("lancedb_table_created", path=str(self.db_path), table=self.table_name, dim=self.dim)

    def _build_schema(self):
        """Build PyArrow schema for the vectors table."""
        import pyarrow as pa
        return pa.schema(
            [
                pa.field("file_id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.dim)),
                pa.field("metadata_json", pa.string()),
            ]
        )

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

        def _do_search():
            query = self._table.search(query_vector).metric("cosine").limit(top_k)
            if filters:
                # LanceDB SQL-like filter
                filter_clauses = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        filter_clauses.append(f"metadata_json LIKE '%\"{key}\":\"{value}\"%'")
                if filter_clauses:
                    query = query.where(" AND ".join(filter_clauses))
            return query.to_list()

        results = await asyncio.to_thread(_do_search)
        return [
            VectorMatch(
                file_id=r["file_id"],
                similarity_score=1.0 - float(r.get("_distance", 0)),  # cosine distance → similarity
                metadata=json.loads(r.get("metadata_json", "{}")),
            )
            for r in results
        ]

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
        Uses to_arrow() (lighter dep than to_pandas() which requires pylance).
        """
        import lancedb

        if self._table is None:
            await self.initialize()

        def _do_merge():
            try:
                other_db = lancedb.connect(other_path)
                other_table = other_db.open_table(self.table_name)
                # Try multiple APIs — lancedb versions differ
                rows = []
                try:
                    # Modern: to_arrow then to_pylist
                    arrow_table = other_table.to_arrow()
                    rows = arrow_table.to_pylist()
                except Exception:
                    try:
                        rows = other_table.to_list()
                    except Exception:
                        # Last resort: search all (limit very high)
                        rows = other_table.search().limit(10**7).to_list()
                if rows:
                    self._table.add(rows)
                return len(rows)
            except Exception as e:
                logger.error("lancedb_merge_failed", from_path=other_path, error=str(e)[:200])
                return 0

        merged = await asyncio.to_thread(_do_merge)
        logger.info("lancedb_merged", from_path=other_path, rows=merged)
        return merged
