"""LLM Router agent — classifies, tags, dedups, decides action.

Receives FileContext (file + embedding + neighbors + existing catalog).
Calls LLM with structured prompt → typed FileDecision.
Applies dedup logic on top of LLM output (deterministic where possible).
3-retry-with-backoff for LLM JSON parsing failures.
"""

from __future__ import annotations

import structlog

from rex.agents.router_classify import RouterClassifyMixin
from rex.agents.router_logic import RouterLogicMixin
from rex.agents.router_prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
    extract_json,
)
from rex.config import Settings, get_settings
from rex.ml.provider import ModelProvider
from rex.models.schemas import (
    DedupStatus,
    FileAction,
    FileContext,
    FileDecision,
)

logger = structlog.get_logger()

# Re-exported for backward-compatible public API.
__all__ = [
    "LLMRouter",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "extract_json",
]


class LLMRouter(RouterLogicMixin, RouterClassifyMixin):
    """LLM-driven file classification + deterministic dedup."""

    MAX_RETRIES = 3

    def __init__(
        self,
        model_provider: ModelProvider,
        settings: Settings | None = None,
    ) -> None:
        self.model = model_provider
        self.settings = settings or get_settings()
        # Project-level context (set by builder when scanning inside a project)
        self.project_context: str = ""
        self.taxonomy_hints: list[str] = []
        self.tag_vocabulary: list[str] = []

    async def route(self, context: FileContext) -> FileDecision:
        """Classify and decide. Applies dedup logic on top of LLM output."""
        # Step 1: dedup check FIRST — cheaper than LLM, deterministic
        dedup_result = self._check_dedup(context)

        # Step 2: LLM classification (we still classify even duplicates,
        # so they have a category for inspection)
        decision = await self._classify_with_retry(context)

        # Step 3: overlay dedup result
        if dedup_result is not None:
            decision.dedup_status = dedup_result.status
            decision.duplicate_of = dedup_result.duplicate_of
            # Duplicates auto-route to trash unless original is missing
            if dedup_result.status == DedupStatus.EXACT_DUPLICATE:
                decision.action = FileAction.TRASH
                if not decision.reasoning.lower().startswith("exact duplicate"):
                    decision.reasoning = f"Exact duplicate of {dedup_result.duplicate_of}; " + decision.reasoning
            elif dedup_result.status == DedupStatus.NEAR_DUPLICATE:
                decision.action = FileAction.ARCHIVE
                decision.reasoning = (
                    f"Near-duplicate of {dedup_result.duplicate_of} "
                    f"(similarity={dedup_result.similarity:.2f}); " + decision.reasoning
                )

        return decision
