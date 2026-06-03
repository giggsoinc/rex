"""Estimation tables + helpers: tokens, cost, time, and Ollama recommendations."""

from __future__ import annotations

# --- Token estimation (rough) ---

AVG_TOKENS_PER_FILE_IN = 800      # prompt + extracted text + context
AVG_TOKENS_PER_FILE_OUT = 150     # FileDecision JSON

# Rough per-million-token costs (cloud LLMs)
COST_PER_MTOK_IN: dict[str, float] = {
    "ollama": 0.0,
    "gemini-2.0-flash-lite": 0.10,
    "gemini-3.1-flash-lite": 0.10,
    "gemini-3.5-flash": 0.30,
    "claude-haiku-4-5-20251001": 1.00,
    "claude-sonnet-4-5": 3.00,
    "anthropic.claude-haiku-4-5-20251001": 1.00,
}
COST_PER_MTOK_OUT: dict[str, float] = {
    "ollama": 0.0,
    "gemini-2.0-flash-lite": 0.40,
    "gemini-3.1-flash-lite": 0.40,
    "gemini-3.5-flash": 2.50,
    "claude-haiku-4-5-20251001": 5.00,
    "claude-sonnet-4-5": 15.00,
    "anthropic.claude-haiku-4-5-20251001": 5.00,
}


def estimate_tokens_and_cost(file_count: int, model: str) -> tuple[int, int, float]:
    """Rough token + cost estimate for a scan."""
    tokens_in = file_count * AVG_TOKENS_PER_FILE_IN
    tokens_out = file_count * AVG_TOKENS_PER_FILE_OUT
    in_rate = COST_PER_MTOK_IN.get(model, 0.0)
    out_rate = COST_PER_MTOK_OUT.get(model, 0.0)
    # Fuzzy match if exact model name not in table
    if in_rate == 0.0 and out_rate == 0.0:
        for k in COST_PER_MTOK_IN:
            if k in model or model in k:
                in_rate = COST_PER_MTOK_IN[k]
                out_rate = COST_PER_MTOK_OUT[k]
                break
    cost = (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate
    return tokens_in, tokens_out, cost


def estimate_seconds(file_count: int, llm_provider: str, parallel_workers: int = 4) -> int:
    """Rough wall-clock estimate.

    Local Ollama ~30s/file sequentially. Cloud APIs ~3s/file with parallel.
    """
    per_file = 30 if llm_provider == "ollama" else 3
    return max(60, int(file_count * per_file / parallel_workers))


# --- Ollama model recommendation ---

OLLAMA_RECOMMENDATIONS: list[tuple[str, str, str]] = [
    # (model, RAM needed, when to use)
    ("qwen3:8b", "~8GB", "Best quality, good speed"),
    ("gemma3:4b", "~4GB", "Fast, smaller RAM"),
    ("dolphin-mistral:latest", "~8GB", "Alt 7B"),
    ("lfm2.5-thinking:latest", "~1GB", "Tiny/fast, lower quality"),
    ("deepseek-r1:8b", "~8GB", "Reasoning-focused"),
]


def list_available_ollama_models() -> list[str]:
    """Best-effort list of pulled Ollama models."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def recommend_ollama_model(installed: list[str]) -> str:
    """Pick the best recommended model from those actually installed."""
    installed_set = {m.lower() for m in installed}
    for model, _, _ in OLLAMA_RECOMMENDATIONS:
        if model.lower() in installed_set or any(model.lower() in inst for inst in installed_set):
            return model
    return installed[0] if installed else "qwen3:8b"
