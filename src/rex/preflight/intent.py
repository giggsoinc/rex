"""ScanIntent — every scan starts with a conversation: what / why / which model.

Asks the user up front so Rex has CONTEXT before it touches a single file.
Output: a typed ScanIntent passed downstream to PreFlight + Planner + Workers.

This module is the stable public entry point; implementation lives in
``intent_model`` (the model), ``intent_estimate`` (token/cost/time + Ollama
recommendations), and ``intent_dialog`` (the interactive gather dialog).
"""

from __future__ import annotations

from rex.preflight.intent_dialog import gather_intent
from rex.preflight.intent_estimate import (
    estimate_seconds,
    estimate_tokens_and_cost,
    list_available_ollama_models,
    recommend_ollama_model,
)
from rex.preflight.intent_model import ScanIntent

__all__ = [
    "ScanIntent",
    "gather_intent",
    "estimate_tokens_and_cost",
    "estimate_seconds",
    "list_available_ollama_models",
    "recommend_ollama_model",
]
