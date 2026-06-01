"""Rex vector store — abstract interface + backend implementations.

Onboarding picks a backend (lancedb local, pgvector/oracle26ai/chromadb enterprise).
All agents talk to VectorStore — never to a specific backend directly.
"""

from rex.vectorstore.base import VectorMatch, VectorStore
from rex.vectorstore.factory import get_vector_store

__all__ = ["VectorStore", "VectorMatch", "get_vector_store"]
