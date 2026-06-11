"""LLM provider step for `rex init` — any LiteLLM-supported provider.

Cloud API keys are written to .env.local under their LiteLLM-standard
names (OPENAI_API_KEY, …) so the routing layer picks them up directly.
"""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt

console = Console()

# provider → (default model, LiteLLM env var for the API key, label)
PROVIDERS: dict[str, tuple[str, str | None, str]] = {
    "ollama":     ("qwen3:8b", None, "local, free"),
    "gemini":     ("gemini-3.1-flash-lite", "GEMINI_API_KEY", "Google"),
    "openai":     ("gpt-4o-mini", "OPENAI_API_KEY", "ChatGPT"),
    "anthropic":  ("claude-haiku-4-5", "ANTHROPIC_API_KEY", "Claude"),
    "xai":        ("grok-3-mini", "XAI_API_KEY", "Grok"),
    "perplexity": ("sonar", "PERPLEXITYAI_API_KEY", "Perplexity"),
    "bedrock":    ("anthropic.claude-haiku-4-5-20251001", None, "AWS creds from env"),
}


def ask_llm_config() -> dict:
    """Ask which LLM provider/model to use for classification."""
    console.print("\n[bold]LLM Provider[/bold]\n")
    for name, (model, _, label) in PROVIDERS.items():
        console.print(f"  [cyan]{name:<11}[/cyan] {label}  [dim](default: {model})[/dim]")

    provider = Prompt.ask(
        "\nWhich LLM for classification?",
        choices=list(PROVIDERS), default="ollama",
    )
    default_model, key_var, _ = PROVIDERS[provider]

    if provider == "ollama":
        endpoint = Prompt.ask("Ollama endpoint", default="http://localhost:11434")
        model = Prompt.ask("Model", default=default_model)
        return {"llm_provider": provider, "llm_endpoint": endpoint, "llm_model": model}

    model = Prompt.ask(f"{provider.capitalize()} model", default=default_model)
    config: dict = {"llm_provider": provider, "llm_model": model}
    if key_var:
        api_key = Prompt.ask(f"{provider.capitalize()} API key", password=True, default="")
        if api_key:
            if provider == "gemini":
                config["gemini_api_key"] = api_key      # legacy REX_ path
            else:
                config[key_var] = api_key               # raw LiteLLM env var
    return config
