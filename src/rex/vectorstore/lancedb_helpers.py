"""Helpers for LanceDBStore — schema building, search formatting, merge logic.

Extracted from lancedb_store.py to keep each module under the line limit.
Pure functions / closures; no LanceDBStore state beyond what's passed in.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from rex.vectorstore.base import VectorMatch

logger = structlog.get_logger()


def build_schema(dim: int):
    """Build PyArrow schema for the vectors table."""
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("file_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("metadata_json", pa.string()),
        ]
    )


def run_search(table: Any, query_vector: list[float], top_k: int, filters: dict | None):
    """Execute a top-k cosine search and return raw LanceDB result rows."""
    query = table.search(query_vector).metric("cosine").limit(top_k)
    if filters:
        # LanceDB SQL-like filter
        filter_clauses = []
        for key, value in filters.items():
            if isinstance(value, str):
                filter_clauses.append(f"metadata_json LIKE '%\"{key}\":\"{value}\"%'")
        if filter_clauses:
            query = query.where(" AND ".join(filter_clauses))
    return query.to_list()


def rows_to_matches(results: list[dict]) -> list[VectorMatch]:
    """Convert raw LanceDB rows into VectorMatch objects."""
    return [
        VectorMatch(
            file_id=r["file_id"],
            similarity_score=1.0 - float(r.get("_distance", 0)),  # cosine distance → similarity
            metadata=json.loads(r.get("metadata_json", "{}")),
        )
        for r in results
    ]


def merge_rows(table: Any, table_name: str, other_path: str) -> int:
    """Read all rows from another LanceDB and add them to ``table``.

    Used by Janitor after parallel workers finish to consolidate shards.
    Uses to_arrow() (lighter dep than to_pandas() which requires pylance).
    """
    import lancedb

    try:
        other_db = lancedb.connect(other_path)
        other_table = other_db.open_table(table_name)
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
            table.add(rows)
        return len(rows)
    except Exception as e:
        logger.error("lancedb_merge_failed", from_path=other_path, error=str(e)[:200])
        return 0
