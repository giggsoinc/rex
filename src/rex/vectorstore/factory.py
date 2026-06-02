"""Vector store factory — returns the right backend based on config."""

from __future__ import annotations

import structlog

from rex.config import Settings, VectorStoreType, get_settings
from rex.vectorstore.base import VectorStore

logger = structlog.get_logger()


def get_vector_store(settings: Settings | None = None) -> VectorStore:
    """Construct the configured VectorStore backend.

    Driven by REX_VECTOR_STORE env var:
      - lancedb (default, local ideation)
      - pgvector (enterprise self-hosted)
      - oracle26ai (enterprise managed)
      - chromadb (enterprise self-hosted)
    """
    s = settings or get_settings()
    store_type = s.vector_store

    logger.info("vector_store_factory", backend=store_type.value)

    if store_type == VectorStoreType.LANCEDB:
        from rex.vectorstore.lancedb_store import LanceDBStore
        return LanceDBStore(db_path=s.vector_path, dim=s.embed_dim)

    if store_type == VectorStoreType.PGVECTOR:
        from rex.vectorstore.pgvector_store import PgVectorStore
        return PgVectorStore(db_url=s.vector_db_url, dim=s.embed_dim)

    if store_type == VectorStoreType.ORACLE26AI:
        from rex.vectorstore.oracle_store import OracleVectorStore
        return OracleVectorStore(
            host=s.vector_host,
            port=s.vector_port,
            service=s.vector_service,
            user=s.vector_user,
            password=s.vector_password,
            dim=s.embed_dim,
        )

    if store_type == VectorStoreType.CHROMADB:
        from rex.vectorstore.chroma_store import ChromaDBStore
        return ChromaDBStore(
            host=s.vector_host,
            port=s.vector_port,
            collection_name=s.vector_collection,
            dim=s.embed_dim,
        )

    raise ValueError(f"Unsupported vector store: {store_type}")
