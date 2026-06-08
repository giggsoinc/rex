"""Evaluation helpers — accuracy / per-class precision / recall / F1.

Lightweight metric implementations to avoid pulling in scikit-learn for
the basic pipeline. For advanced evaluation (calibration, ROC, slice
metrics), swap to sklearn / evaluate libraries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

__all__ = ["MetricReport", "score_predictions"]


@dataclass
class MetricReport:
    """Summary of classifier quality on a held-out set."""

    accuracy: float = 0.0
    macro_f1: float = 0.0
    per_class: dict[str, dict[str, float]] = field(default_factory=dict)
    n: int = 0
    correct: int = 0

    def as_dict(self) -> dict:
        """Serialize for logging or dashboard rendering."""
        return {
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {k: {m: round(v, 4) for m, v in s.items()}
                          for k, s in self.per_class.items()},
            "n": self.n,
            "correct": self.correct,
        }


def _f1(precision: float, recall: float) -> float:
    """F1 = harmonic mean of precision and recall."""
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_predictions(
    predicted: list[str], truth: list[str],
) -> MetricReport:
    """Compute accuracy, per-class precision/recall/F1, and macro F1.

    Args:
        predicted: list of predicted labels
        truth:     list of ground-truth labels (same length and order)

    Returns:
        MetricReport.
    """
    if len(predicted) != len(truth):
        raise ValueError(f"length mismatch: {len(predicted)} vs {len(truth)}")
    if not predicted:
        return MetricReport()

    n = len(predicted)
    correct = sum(p == t for p, t in zip(predicted, truth))
    accuracy = correct / n

    # Per-class TP / FP / FN
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for p, t in zip(predicted, truth):
        if p == t:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1

    classes = set(predicted) | set(truth)
    per_class: dict[str, dict[str, float]] = {}
    f1_scores: list[float] = []
    for c in classes:
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1 = _f1(prec, rec)
        f1_scores.append(f1)
        per_class[c] = {
            "precision": prec, "recall": rec, "f1": f1,
            "support": tp[c] + fn[c],
        }
    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0

    return MetricReport(
        accuracy=accuracy, macro_f1=macro_f1, per_class=per_class, n=n, correct=correct,
    )
