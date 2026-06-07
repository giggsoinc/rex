"""Classifier registry — name-keyed factory for swappable algorithms.

Algorithms register themselves at import time. Pipeline + config consume
classifiers by string name (knn / bertopic / setfit / llm_zero_shot / ensemble).

Usage:
  from rex.ml.classifier import get_classifier
  clf = get_classifier("knn", k=5, lance_path="~/rex-data/vectors.lance")
  clf.fit(labeled_examples)
  pred = clf.predict(query_embedding)
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from rex.ml.classifier.base import Classifier

logger = structlog.get_logger()

__all__ = ["ClassifierRegistry", "register_classifier", "get_classifier"]

ClassifierFactory = Callable[..., Classifier]


class ClassifierRegistry:
    """Singleton-style registry mapping algorithm name → factory callable."""

    _registry: dict[str, ClassifierFactory] = {}

    @classmethod
    def register(cls, name: str, factory: ClassifierFactory) -> None:
        """Register a classifier factory under a string name."""
        if name in cls._registry:
            logger.warning("classifier_re_registered", name=name)
        cls._registry[name] = factory

    @classmethod
    def get(cls, name: str, **kwargs: Any) -> Classifier:
        """Instantiate a classifier by name, passing kwargs to its factory."""
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry)) or "(none — import algorithms first)"
            raise KeyError(
                f"Classifier '{name}' not registered. Available: {available}"
            )
        return cls._registry[name](**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered classifier names."""
        return sorted(cls._registry)

    @classmethod
    def reset(cls) -> None:
        """Clear the registry — primarily for tests."""
        cls._registry.clear()


def register_classifier(name: str) -> Callable[[ClassifierFactory], ClassifierFactory]:
    """Decorator to register a classifier factory.

    Example:
        @register_classifier("knn")
        def make_knn(k: int = 5, ...) -> KNNClassifier:
            return KNNClassifier(k=k, ...)
    """

    def _decorator(factory: ClassifierFactory) -> ClassifierFactory:
        ClassifierRegistry.register(name, factory)
        return factory

    return _decorator


def get_classifier(name: str, **kwargs: Any) -> Classifier:
    """Top-level convenience resolver — equivalent to ClassifierRegistry.get."""
    # Trigger lazy import of bundled algorithms so they self-register.
    from rex.ml.classifier import algorithms  # noqa: F401
    return ClassifierRegistry.get(name, **kwargs)
