"""ClassifierRouter — RouterAgent backed by the plug-and-play classifier module.

Drop-in replacement for the LLMRouter. Uses any Classifier (kNN / LLM
zero-shot / ensemble) to produce FileDecision objects from FileContext.

Why this exists:
  - LLMRouter is one LLM call per file → slow, expensive.
  - ClassifierRouter routes through the ensemble path → kNN-fast + LLM-honest.
  - Same RouterAgent Protocol → pipeline doesn't care which is wired.

Builder.py decides which router to use based on settings / BusinessContext.
"""

from __future__ import annotations

from typing import Any

import structlog

from rex.agents.router_classify import RouterClassifyMixin
from rex.ml.classifier.base import Classifier
from rex.models.schemas import (
    DedupStatus,
    FileAction,
    FileContext,
    FileDecision,
)

logger = structlog.get_logger()

__all__ = ["ClassifierRouter"]


class ClassifierRouter(RouterClassifyMixin):
    """Pluggable classifier-driven Router.

    Inherits RouterClassifyMixin so dedup + default-category fallback stay
    consistent with the legacy LLMRouter path.
    """

    def __init__(
        self,
        classifier: Classifier,
        settings: Any | None = None,
    ) -> None:
        """Construct with an already-built Classifier (kNN, ensemble, etc.)."""
        self.classifier = classifier
        self.settings = settings
        # Optional fields LLMRouter sets — kept for Protocol compatibility
        self.project_context: str = ""
        self.taxonomy_hints: list[str] = []
        self.tag_vocabulary: list[str] = []

    async def route(self, context: FileContext) -> FileDecision:
        """Classify + dedup. Same contract as LLMRouter.route()."""
        # Dedup first — cheaper than classification, deterministic
        dedup_result = self._check_dedup(context)

        # Pull embedding from the FileContext (Scanner stored it after embed)
        embedding = getattr(context, "embedding", None) or []
        text = (context.file_record.extracted_text or "")[:1500]

        # Run the classifier — pass both embedding (kNN) and text (LLM)
        try:
            pred = self.classifier.predict(embedding, text=text)
        except Exception as e:
            logger.warning(
                "classifier_router_failed",
                file=context.file_record.filename,
                error=str(e)[:200],
            )
            return self._fallback(context)

        decision = FileDecision(
            category=pred.category,
            tags=self._infer_tags(pred),
            relevance=4,  # keep-by-default; tune via separate relevance model later
            action=FileAction.KEEP,
            reasoning=f"{pred.source}: {pred.meta.get('reason', 'classified')}",
            confidence=pred.confidence,
            duplicate_of=None,
            dedup_status=DedupStatus.UNIQUE,
        )

        # Apply dedup overlay (same as LLMRouter)
        if dedup_result is not None:
            decision.dedup_status = dedup_result.status
            decision.duplicate_of = dedup_result.duplicate_of
            if dedup_result.status == DedupStatus.EXACT_DUPLICATE:
                decision.action = FileAction.TRASH
                decision.reasoning = (
                    f"Exact duplicate of {dedup_result.duplicate_of}; "
                    + decision.reasoning
                )
            elif dedup_result.status == DedupStatus.NEAR_DUPLICATE:
                decision.action = FileAction.ARCHIVE
                decision.reasoning = (
                    f"Near-duplicate ({dedup_result.similarity:.2f}); "
                    + decision.reasoning
                )

        return decision

    def _infer_tags(self, pred) -> list[str]:
        """Cheap tag inference — top-3 candidates from the classifier output."""
        tags = [
            label.lower().replace(" ", "-")[:20]
            for label, _ in pred.candidates[:3]
        ]
        if pred.source:
            tags.append(f"src-{pred.source.replace('_', '-')}")
        return tags[:5]

    def _fallback(self, context: FileContext) -> FileDecision:
        """When classifier errors entirely — default category by media type."""
        category = self._infer_default_category(context)
        return FileDecision(
            category=category,
            tags=["unclassified"],
            relevance=3,
            action=FileAction.KEEP,
            reasoning="Classifier unavailable; default by media type.",
            confidence=0.3,
            duplicate_of=None,
            dedup_status=DedupStatus.UNIQUE,
        )
