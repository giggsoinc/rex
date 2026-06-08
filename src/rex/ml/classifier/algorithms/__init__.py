"""Bundled classifier algorithms — import-time self-registration.

Importing this package triggers each algorithm module to call
@register_classifier(...) so the registry knows about it.
"""

from __future__ import annotations

# Import each algorithm so its @register_classifier decorator fires.
from rex.ml.classifier.algorithms import knn  # noqa: F401
from rex.ml.classifier.algorithms import llm_zero_shot  # noqa: F401
from rex.ml.classifier.algorithms import ensemble  # noqa: F401

# Future algorithms wire in the same way:
# from rex.ml.classifier.algorithms import bertopic, setfit
