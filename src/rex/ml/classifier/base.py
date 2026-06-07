"""Classifier Protocol + typed Prediction value object.

All Rex classifier algorithms (kNN, BERTopic, SetFit, LLM zero-shot, ensemble)
implement the Classifier Protocol. The pipeline doesn't care which algorithm
runs — it only sees Prediction objects with a uniform (category, confidence,
source) shape.

Why a Protocol (not ABC):
  - Lets third-party algorithms plug in without inheriting from a Rex base
  - Plays well with mypy structural typing
  - Easy to mock in tests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["Classifier", "Prediction"]


@dataclass
class Prediction:
    """Typed classifier output — uniform across algorithms.

    Fields:
        category:    the chosen label
        confidence:  0-1 confidence; <threshold → _Review/
        source:      algorithm name (knn / bertopic / setfit / llm_zero_shot / ensemble)
        candidates:  ranked list of (label, score) for explainability
        meta:        algorithm-specific debug info (e.g., k=5 votes breakdown)
    """

    category: str
    confidence: float
    source: str
    candidates: list[tuple[str, float]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for logging / decision history."""
        return {
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "candidates": self.candidates,
            "meta": self.meta,
        }


@runtime_checkable
class Classifier(Protocol):
    """Every Rex classifier implements this minimal interface."""

    name: str

    def fit(self, examples: list[tuple[list[float], str]]) -> None:
        """Train / index labeled examples — (embedding, label) tuples.

        Algorithms that don't need training (zero-shot LLM) implement as no-op.
        """
        ...

    def predict(self, embedding: list[float], **kwargs: Any) -> Prediction:
        """Classify a single embedding. Must populate Prediction.source = self.name."""
        ...

    def explain(self, embedding: list[float]) -> dict[str, Any]:
        """Return human-readable rationale for predict() output.

        Default contract: returns at minimum {"name": self.name, "version": ...}.
        Algorithms should add neighbors / probabilities / topic words / prompts.
        """
        ...
