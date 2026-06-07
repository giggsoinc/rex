"""LLM zero-shot classifier — asks LLM to pick from candidate labels.

Cold-start: no training. Pairs with kNN (zero-shot first → kNN as labels grow
→ ensemble). Prompts for JSON {label, confidence, reason}; clamps to [0, 1].
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from rex.config import Settings, get_settings
from rex.ml.classifier.base import Prediction
from rex.ml.classifier.registry import register_classifier
from rex.ml.provider import ModelProvider

logger = structlog.get_logger()

__all__ = ["LLMZeroShotClassifier", "make_llm_zero_shot"]


_SYSTEM = """You are a strict text classifier.

You receive: a piece of TEXT and a list of CANDIDATE LABELS.
You MUST return ONLY valid JSON:
  {"label": "<one of CANDIDATE LABELS>",
   "confidence": <float 0.0 to 1.0>,
   "reason": "<one-sentence justification>"}

Rules:
- The label MUST be exactly one of the candidates — no inventing new labels.
- Confidence: be honest. Inflated scores hurt the user. Use 0.5 if uncertain.
- Reason must be one sentence, plain English, citing evidence.
"""


def _build_prompt(text: str, candidates: list[str]) -> str:
    """Compose the user prompt for the LLM zero-shot classifier."""
    return (
        f"CANDIDATE LABELS: {', '.join(candidates)}\n\n"
        f"TEXT:\n{text[:1500]}\n\n"
        f"Return JSON now."
    )


def _extract_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response — tolerant of prose."""
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


class LLMZeroShotClassifier:
    """Zero-shot text classification — no training required."""

    name = "llm_zero_shot"

    def __init__(
        self,
        candidates: list[str] | None = None,
        model_provider: ModelProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Init with optional starting candidates and an injected model."""
        self.candidates = list(candidates or [])
        self.settings = settings or get_settings()
        self.model = model_provider or ModelProvider(self.settings)

    def fit(self, examples: list[tuple[list[float], str]]) -> None:
        """Zero-shot has no training step; we adopt the example labels as candidates."""
        labels = {label for _, label in examples}
        if labels:
            self.candidates = sorted(set(self.candidates) | labels)
        logger.info("llm_zero_shot_candidates", candidates=self.candidates)

    def set_candidates(self, labels: list[str]) -> None:
        """Explicitly set the candidate label set."""
        self.candidates = list(labels)

    async def predict_async(self, text: str, **_: Any) -> Prediction:
        """Classify the given text into one of self.candidates."""
        if not self.candidates:
            return Prediction(
                category="_Unsorted", confidence=0.0, source=self.name,
                meta={"reason": "no candidate labels configured"},
            )

        prompt = _build_prompt(text, self.candidates)
        try:
            raw = await self.model.generate(prompt, system=_SYSTEM, json_mode=True)
            data = _extract_json(raw)
        except Exception as e:
            logger.warning("llm_zero_shot_failed", error=str(e)[:200])
            return Prediction(
                category="_Unsorted", confidence=0.0, source=self.name,
                meta={"error": str(e)[:200]},
            )

        label = str(data.get("label", "")).strip()
        if label not in self.candidates:
            return Prediction(
                category="_Unsorted", confidence=0.0, source=self.name,
                meta={"rejected_label": label, "reason": "LLM hallucinated label"},
            )
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        return Prediction(
            category=label, confidence=confidence, source=self.name,
            meta={"reason": str(data.get("reason", ""))[:200]},
        )

    def predict(self, embedding: list[float], text: str = "", **kwargs: Any) -> Prediction:
        """Synchronous predict — runs the async LLM call in an event loop."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.predict_async(text or "(no text supplied)")
        )

    def explain(self, embedding: list[float]) -> dict[str, Any]:
        """Return a static explainer — LLM zero-shot is opaque per call."""
        return {
            "name": self.name,
            "candidates": self.candidates,
            "note": "Zero-shot; predict() uses LLM. See per-call .meta.reason for rationale.",
        }


@register_classifier("llm_zero_shot")
def make_llm_zero_shot(
    candidates: list[str] | None = None,
    model_provider: ModelProvider | None = None,
    **_: Any,
) -> LLMZeroShotClassifier:
    """Factory — registered as 'llm_zero_shot'."""
    return LLMZeroShotClassifier(candidates=candidates, model_provider=model_provider)
