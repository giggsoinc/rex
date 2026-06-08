"""Ensemble classifier — weighted vote across registered classifiers.

Combines predictions from multiple algorithms (kNN + LLM zero-shot + BERTopic
+ SetFit, etc.) into a single Prediction with consensus confidence.

Weighting strategy:
  - User-provided fixed weights (default), OR
  - Auto-tuned from per-algo F1 (future, via lifecycle/eval.py)

Voting:
  - Each member returns (category, confidence)
  - Score per label = sum(weight * confidence) across members that voted
  - Winner = highest aggregate score
  - Ensemble confidence = winner_score / sum_of_all_scores

Disagreement metric (entropy) signals "should I really trust this?" — if
members disagree, even a high score is suspect.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import structlog

from rex.ml.classifier.base import Classifier, Prediction
from rex.ml.classifier.registry import register_classifier

logger = structlog.get_logger()

__all__ = ["EnsembleClassifier", "make_ensemble"]


def _entropy(probs: list[float]) -> float:
    """Shannon entropy over a probability distribution — uncertainty metric."""
    return -sum(p * math.log2(p) for p in probs if p > 0)


class EnsembleClassifier:
    """Weighted vote across a list of Classifier members."""

    name = "ensemble"

    def __init__(
        self,
        members: list[Classifier],
        weights: list[float] | None = None,
    ) -> None:
        """Construct an ensemble from already-instantiated classifier members."""
        if not members:
            raise ValueError("ensemble needs ≥1 member")
        self.members = members
        # Normalize weights to sum to 1.0 (default = equal)
        if weights is None:
            weights = [1.0 / len(members)] * len(members)
        if len(weights) != len(members):
            raise ValueError("weights length must match members")
        total = sum(weights) or 1.0
        self.weights = [w / total for w in weights]

    def fit(self, examples: list[tuple[list[float], str]]) -> None:
        """Forward training data to every member that can use it."""
        for m in self.members:
            try:
                m.fit(examples)
            except Exception as e:
                logger.warning("ensemble_member_fit_failed", member=m.name, error=str(e)[:200])

    def predict(self, embedding: list[float], **kwargs: Any) -> Prediction:
        """Run all members; aggregate by weighted vote on category."""
        scores: dict[str, float] = defaultdict(float)
        per_member: dict[str, Prediction] = {}

        for m, w in zip(self.members, self.weights):
            try:
                p = m.predict(embedding, **kwargs)
            except Exception as e:
                logger.warning("ensemble_member_failed", member=m.name, error=str(e)[:200])
                continue
            per_member[m.name] = p
            scores[p.category] += w * p.confidence

        if not scores:
            return Prediction(
                category="_Unsorted", confidence=0.0, source=self.name,
                meta={"reason": "all members failed"},
            )

        total_score = sum(scores.values()) or 1.0
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winner, winner_score = ranked[0]
        ensemble_conf = winner_score / total_score

        # Disagreement = entropy of normalized score distribution
        probs = [s / total_score for s in scores.values()]
        disagreement = _entropy(probs)

        return Prediction(
            category=winner,
            confidence=ensemble_conf,
            source=self.name,
            candidates=[(lbl, round(s / total_score, 4)) for lbl, s in ranked],
            meta={
                "members": {n: p.as_dict() for n, p in per_member.items()},
                "weights": dict(zip([m.name for m in self.members], self.weights)),
                "disagreement_entropy": round(disagreement, 4),
            },
        )

    def explain(self, embedding: list[float]) -> dict[str, Any]:
        """Show per-member predictions for the same query."""
        return {
            "name": self.name,
            "members": [m.name for m in self.members],
            "weights": self.weights,
            "prediction": self.predict(embedding).as_dict(),
        }


@register_classifier("ensemble")
def make_ensemble(
    members: list[Classifier], weights: list[float] | None = None, **_: Any,
) -> EnsembleClassifier:
    """Factory — registered as 'ensemble'."""
    return EnsembleClassifier(members=members, weights=weights)
