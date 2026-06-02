"""Rex configuration enums — provider/backend/mode/profile choices."""

from __future__ import annotations

from enum import Enum


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OLLAMA = "ollama"
    GEMINI = "gemini"
    BEDROCK = "bedrock"
    OPENAI = "openai"


class VisionProvider(str, Enum):
    """Supported vision providers."""

    GEMINI = "gemini"
    OPENAI = "openai"
    NONE = "none"


class StorageBackend(str, Enum):
    """Output storage backend options."""

    LOCAL = "local"
    S3 = "s3"


class DeploymentMode(str, Enum):
    """Deployment mode chosen during onboarding."""

    LOCAL = "local"
    ENTERPRISE = "enterprise"


class VectorStoreType(str, Enum):
    """Vector store backends."""

    LANCEDB = "lancedb"
    PGVECTOR = "pgvector"
    ORACLE26AI = "oracle26ai"
    CHROMADB = "chromadb"


class RexProfile(str, Enum):
    """Resource profile for model selection."""

    FULL = "full"       # qwen3:8b
    LIGHT = "light"     # gemma3:4b — fits on 16GB laptops
