"""ScanIntent model — typed user intent captured before a scan begins."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScanIntent(BaseModel):
    """User intent captured before scan begins."""

    purpose: str = Field(description="What is the user doing (one-liner)")
    goal: str = Field(description="Desired outcome — what 'success' looks like")
    llm_provider: str = Field(default="ollama")
    llm_model: str = Field(default="qwen3:8b")
    estimated_files: int = 0
    estimated_total_bytes: int = 0
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    estimated_seconds: int = 0
    accept_soft_warnings: bool = Field(default=False, description="If True, PreFlight soft-fails proceed without prompt")
