"""kNN classifier — k-nearest-neighbor vote on an in-memory labeled index.

Why kNN as default:
  - Zero training cost; learns incrementally as user labels in HITL Review.
  - Uses the embeddings Rex already computes (LanceDB or in-memory).
  - Confidence comes naturally from vote consensus.
  - Predictions are explainable — show the actual neighbors that voted.

In-memory index keeps things simple for ≤100k files. For larger corpora,
swap the brute-force search for LanceDB ANN (see lance_search()).

Distance metric: cosine similarity (vectors are typically unit-normalized).
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Any

import structlog

from rex.ml.classifier.base import Prediction
from rex.ml.classifier.registry import register_classifier

logger = structlog.get_logger()

__all__ = ["KNNClassifier", "make_knn"]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity — assumes equal length, returns [-1, 1]."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class KNNClassifier:
    """k-Nearest-Neighbor classifier using cosine similarity.

    Labels arrive via fit() / add() — append-only, so HITL corrections take
    effect on the next predict() call without retraining.
    """

    name = "knn"

    def __init__(self, k: int = 5, min_neighbors: int = 1) -> None:
        """Init with neighborhood size k and minimum vote-floor."""
        self.k = k
        self.min_neighbors = min_neighbors
        # (embedding, label) pairs; in-memory for now
        self._index: list[tuple[list[float], str]] = []

    def fit(self, examples: list[tuple[list[float], str]]) -> None:
        """Replace the in-memory index with the provided labeled examples."""
        self._index = list(examples)
        logger.info("knn_indexed", count=len(self._index), k=self.k)

    def add(self, embedding: list[float], label: str) -> None:
        """Append a single labeled example — used by the HITL learning loop."""
        self._index.append((embedding, label))

    def size(self) -> int:
        """Return number of labeled examples in the index."""
        return len(self._index)

    def predict(self, embedding: list[float], **_: Any) -> Prediction:
        """Vote of the top-k cosine neighbors. Confidence = winner_count / k."""
        if not self._index:
            return Prediction(
                category="_Unsorted",
                confidence=0.0,
                source=self.name,
                meta={"reason": "empty index — no labeled examples yet"},
            )

        # Top-k by cosine similarity (max-heap via negation)
        scored = ((_cosine(embedding, vec), label) for vec, label in self._index)
        top = heapq.nlargest(self.k, scored, key=lambda x: x[0])
        votes = Counter(label for _, label in top)
        winner, winner_votes = votes.most_common(1)[0]

        confidence = winner_votes / max(len(top), 1)
        candidates = [(lbl, c / max(len(top), 1)) for lbl, c in votes.most_common()]

        return Prediction(
            category=winner,
            confidence=confidence,
            source=self.name,
            candidates=candidates,
            meta={
                "k_effective": len(top),
                "k_requested": self.k,
                "vote_breakdown": dict(votes),
                "neighbor_scores": [round(s, 4) for s, _ in top],
            },
        )

    def explain(self, embedding: list[float]) -> dict[str, Any]:
        """Return predict() output + top-k neighbor labels and scores."""
        pred = self.predict(embedding)
        return {
            "name": self.name,
            "k": self.k,
            "index_size": self.size(),
            "prediction": pred.as_dict(),
        }


@register_classifier("knn")
def make_knn(k: int = 5, min_neighbors: int = 1, **_: Any) -> KNNClassifier:
    """Factory function — registered as 'knn' in ClassifierRegistry."""
    return KNNClassifier(k=k, min_neighbors=min_neighbors)
