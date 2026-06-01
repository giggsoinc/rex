"""Network PreFlight probes — Ollama, embeddings, Gemini.

Re-exports the filesystem probes so callers can import all probes from one place.
"""

from __future__ import annotations

import asyncio

from rex.config import Settings, VisionProvider
from rex.preflight.checks_models import CheckResult, CheckStatus
from rex.preflight.checks_probes_fs import (
    _human_size,
    _noop_check,
    check_deps,
    check_disk,
    check_lancedb_writable,
    check_source,
)

__all__ = [
    "check_ollama",
    "check_embed_model",
    "check_gemini",
    "check_disk",
    "check_lancedb_writable",
    "check_deps",
    "check_source",
    "_noop_check",
    "_human_size",
]


async def check_ollama(settings: Settings, model_name: str) -> CheckResult:
    """Verify Ollama is reachable and the model is pulled."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.llm_endpoint}/api/tags")
        if r.status_code != 200:
            return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                               f"API returned {r.status_code}",
                               {"endpoint": settings.llm_endpoint})
        models = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(model_name.split(":")[0] in m for m in models):
            return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                               f"Model '{model_name}' not pulled. Available: {models[:5]}",
                               {"available": models, "needed": model_name})
        return CheckResult("Ollama", CheckStatus.OK,
                           f"Reachable, '{model_name}' available",
                           {"models_count": len(models)})
    except Exception as e:
        return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                           f"Cannot reach Ollama: {str(e)[:120]}",
                           {"endpoint": settings.llm_endpoint})


async def check_embed_model(settings: Settings) -> CheckResult:
    """Verify embedding model is available."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.llm_endpoint}/api/tags")
        if r.status_code != 200:
            return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                               "Cannot list Ollama models for embeddings")
        models = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(settings.embed_model.split(":")[0] in m for m in models):
            return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                               f"Embedding model '{settings.embed_model}' not pulled",
                               {"needed": settings.embed_model})
        return CheckResult("Embeddings", CheckStatus.OK,
                           f"'{settings.embed_model}' ready")
    except Exception as e:
        return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                           f"Embed check failed: {str(e)[:120]}")


async def check_gemini(settings: Settings) -> CheckResult:
    """Verify Gemini API key (for vision)."""
    if settings.vision_provider == VisionProvider.NONE:
        return CheckResult("Gemini", CheckStatus.OK, "Vision disabled (skip)")
    if not settings.gemini_api_key:
        return CheckResult("Gemini", CheckStatus.SOFT_WARN,
                           "No Gemini key — image vision will be skipped",
                           {"fix": "Set GEMINI_API_KEY in .env to enable"})
    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        # Light test — just list models
        await asyncio.to_thread(client.models.list)
        return CheckResult("Gemini", CheckStatus.OK, "API key valid")
    except Exception as e:
        return CheckResult("Gemini", CheckStatus.SOFT_WARN,
                           f"Gemini key set but failed test: {str(e)[:80]}",
                           {"fix": "Verify GEMINI_API_KEY value"})
