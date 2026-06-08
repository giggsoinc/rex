"""Classifier lifecycle — training, evaluation, drift detection, snapshots.

Public surface:
  - DriftReport (dataclass) + scan_drift(prior_state, output_root)
  - bootstrap_from_decisions(decisions_dir) → list[(embedding, label)]
  - score_predictions(predictions, ground_truth) → MetricReport
"""

from __future__ import annotations

from rex.ml.classifier.lifecycle.drift_detector import DriftReport, scan_drift
from rex.ml.classifier.lifecycle.eval import MetricReport, score_predictions
from rex.ml.classifier.lifecycle.train import bootstrap_from_decisions

__all__ = [
    "DriftReport",
    "scan_drift",
    "MetricReport",
    "score_predictions",
    "bootstrap_from_decisions",
]
