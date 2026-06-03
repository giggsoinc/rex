"""Rex configuration — all env vars, typed and validated."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

from rex.config_enums import (
    DeploymentMode,
    LLMProvider,
    RexProfile,
    StorageBackend,
    VectorStoreType,
    VisionProvider,
)
from rex.config_env import find_env_files

__all__ = [
    "LLMProvider",
    "VisionProvider",
    "StorageBackend",
    "DeploymentMode",
    "VectorStoreType",
    "RexProfile",
    "Settings",
    "get_settings",
]


class Settings(BaseSettings):
    """Rex application settings — loaded from environment variables."""

    # Deployment
    deployment_mode: DeploymentMode = DeploymentMode.LOCAL

    # LLM
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    llm_endpoint: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    embed_model: str = "all-minilm:latest"
    embed_dim: int = Field(default=384, description="Embedding dimension (384 for all-minilm)")
    profile: RexProfile = RexProfile.FULL

    # Vision
    vision_provider: VisionProvider = VisionProvider.GEMINI
    vision_model: str = "gemini-2.0-flash-lite"
    gemini_api_key: str = ""

    # Vector store
    vector_store: VectorStoreType = VectorStoreType.LANCEDB
    vector_path: str = "~/rex-data/vectors.lance"          # for LanceDB local
    vector_db_url: str = ""                                # for pgvector
    vector_host: str = ""                                  # for Oracle/Chroma
    vector_port: int = 0
    vector_db: str = ""
    vector_service: str = ""                               # for Oracle
    vector_user: str = ""
    vector_password: str = ""
    vector_collection: str = "rex_vectors"                 # for Chroma

    # Metadata storage (only for enterprise; local uses SQLite-lite or LanceDB itself)
    db_url: str = "sqlite+aiosqlite:///~/rex-data/rex.db"

    # Output storage
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_path: str = "~/rex-data/output"

    # Processing
    max_text_chars: int = Field(default=2000)
    dedup_exact_threshold: float = Field(default=1.0)
    dedup_near_threshold: float = Field(default=0.92)
    dedup_related_threshold: float = Field(default=0.80)
    batch_size: int = Field(default=10)
    ollama_parallel: int = Field(default=4)

    # Secret provider
    secret_provider: str = "file"
    secret_file_path: str = ".raven/manifest.secrets.json"
    secret_env_prefix: str = "REX_"
    secret_prefix: str = "/rex/prod/"           # AWS/Azure/GCP/OCI prefix
    secret_region: str = "us-east-1"            # AWS region
    secret_vault_url: str = ""                  # Azure/Vault URL
    secret_vault_token: str = ""                # HashiCorp Vault token (dev)
    secret_vault_id: str = ""                   # OCI Vault OCID
    secret_compartment_id: str = ""             # OCI compartment OCID
    secret_project_id: str = ""                 # GCP project ID

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "pretty"] = "pretty"

    model_config = {"env_prefix": "REX_", "env_file": ".env.local", "extra": "ignore"}


def get_settings() -> Settings:
    """Get validated Rex settings from environment.

    Loads dotenv files found across CWD / repo root / ~/.rex (CWD wins),
    and accepts GEMINI_ADK_KEY / GOOGLE_API_KEY as fallback for gemini_api_key.
    """
    import os
    from dotenv import load_dotenv

    # Load every discovered env file. override=False → first (highest-priority) wins.
    for env_file in find_env_files():
        load_dotenv(env_file, override=False)

    s = Settings()

    if not s.gemini_api_key:
        s.gemini_api_key = (
            os.environ.get("REX_GEMINI_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GEMINI_ADK_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        )
    return s
