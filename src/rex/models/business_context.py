"""Business context — captured per scan at onboarding time.

Drives category alignment, confidence thresholds, and model routing for the
two-phase sort + graph pipeline. Lives in its own module so schemas.py stays
under the 150-line guard.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

__all__ = ["BusinessContext", "ModelProfile"]


class ModelProfile(str, Enum):
    """Per-folder model profile picker — chosen at onboarding."""

    LOCAL = "local"          # Ollama only (free, slower)
    BALANCED = "balanced"    # Gemini + local mix (default)
    PREMIUM = "premium"      # Claude / GPT-4 (best quality)
    CUSTOM = "custom"        # User picks per stage


class BusinessContext(BaseModel):
    """Per-folder business context — captured at onboarding.

    Drives category alignment, confidence thresholds, model routing.
    Persisted at .raven/business_context.json (per project) or
    ~/rex-data/contexts/{job_id}.json (per scan).
    """

    business: str = Field(description="One-sentence description of the business / purpose")
    domains: list[str] = Field(
        default_factory=list,
        description="Key domains user cares about — Marketing, Sales, Finance, etc.",
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Below this, files route to _Review/ for HITL triage",
    )
    model_profile: ModelProfile = Field(default=ModelProfile.BALANCED)
    build_knowledge_graph: bool = Field(
        default=True,
        description="If True, run entity extraction + graph build with sort",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
