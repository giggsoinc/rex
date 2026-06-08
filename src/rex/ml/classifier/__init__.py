"""Rex classifier module — plug-and-play classification algorithms.

Architecture (see docs/diagrams/classification-pipeline.html):

  Embed (LanceDB) → Classifier ensemble → Confidence + category
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
       kNN          BERTopic           LLM zero-shot
        │                 │                  │
        └────── Ensemble Voter ──────────────┘
                  (weighted)
                          │
                          ▼
                  (category, confidence)

Public surface:
  - Classifier (Protocol) — every algorithm implements predict() / fit() / explain()
  - Prediction (dataclass) — typed return value (category, confidence, source)
  - ClassifierRegistry — name-keyed factory (YAML / config driven)
  - get_classifier(name) — convenience top-level resolver
"""

from __future__ import annotations

from rex.ml.classifier.base import Classifier, Prediction
from rex.ml.classifier.registry import ClassifierRegistry, get_classifier

__all__ = [
    "Classifier",
    "Prediction",
    "ClassifierRegistry",
    "get_classifier",
]
