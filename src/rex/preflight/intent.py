"""ScanIntent — every scan starts with a conversation: what / why / which model.

Asks the user up front so Rex has CONTEXT before it touches a single file.
Output: a typed ScanIntent passed downstream to PreFlight + Planner + Workers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from rex.config import LLMProvider, get_settings

console = Console()


class ScanIntent(BaseModel):
    """User intent captured before scan begins."""

    purpose: str = Field(description="What is the user doing (one-liner)")
    goal: str = Field(description="Desired outcome — what 'success' looks like")
    llm_provider: str = Field(default="ollama")
    llm_model: str = Field(default="qwen3:8b")
    estimated_files: int = 0
    estimated_total_bytes: int = 0
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    estimated_seconds: int = 0
    accept_soft_warnings: bool = Field(default=False, description="If True, PreFlight soft-fails proceed without prompt")


# --- Token estimation (rough) ---

AVG_TOKENS_PER_FILE_IN = 800      # prompt + extracted text + context
AVG_TOKENS_PER_FILE_OUT = 150     # FileDecision JSON

# Rough per-million-token costs (cloud LLMs)
COST_PER_MTOK_IN: dict[str, float] = {
    "ollama": 0.0,
    "gemini-2.0-flash": 0.10,
    "gemini-3.1-flash-lite": 0.10,
    "gemini-3.5-flash": 0.30,
    "claude-haiku-4-5-20251001": 1.00,
    "claude-sonnet-4-5": 3.00,
    "anthropic.claude-haiku-4-5-20251001": 1.00,
}
COST_PER_MTOK_OUT: dict[str, float] = {
    "ollama": 0.0,
    "gemini-2.0-flash": 0.40,
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


# --- The dialog ---

def gather_intent(
    *,
    source_path: str,
    file_count_estimate: int,
    bytes_estimate: int,
    purpose: Optional[str] = None,
    goal: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    parallel_workers: int = 4,
    non_interactive: bool = False,
) -> ScanIntent:
    """Interactive dialog to gather scan intent.

    Asks every run unless `non_interactive=True` AND all args provided.
    Always returns a ScanIntent with token + cost estimates filled in.
    """
    # If completely non-interactive or stdin is not a TTY
    headless = non_interactive or not sys.stdin.isatty()

    settings = get_settings()
    llm_provider = llm_provider or settings.llm_provider.value
    llm_model = llm_model or settings.llm_model

    if not headless:
        console.print(Panel.fit(
            "[bold cyan]Rex Scan — Intent Dialog[/bold cyan]\n"
            "[dim]Tell Rex what this scan is for. Better context = better classification.[/dim]",
            border_style="cyan",
        ))
        console.print(f"\n[bold]Source:[/bold] {source_path}")
        console.print(f"[bold]Estimated:[/bold] ~{file_count_estimate:,} files, "
                      f"~{_human_size(bytes_estimate)}")
        console.print()

    if not purpose:
        if headless:
            purpose = f"Scan {Path(source_path).name}"
        else:
            purpose = Prompt.ask(
                "[bold]1. What are you doing?[/bold] (one-liner)",
                default=f"Organizing files from {Path(source_path).name}",
            )
    if not goal:
        if headless:
            goal = "Organize, dedupe, categorize"
        else:
            goal = Prompt.ask(
                "[bold]2. What's the goal?[/bold] (what should success look like)",
                default="Discover categories, surface duplicates, build a searchable catalog",
            )

    # LLM provider + model
    if not headless and llm_provider is None:
        llm_provider = Prompt.ask(
            "[bold]3. LLM provider[/bold]",
            choices=["ollama", "gemini", "bedrock"],
            default="ollama",
        )

    if llm_provider == "ollama":
        installed = list_available_ollama_models()
        if not llm_model or llm_model not in installed:
            if not installed:
                if not headless:
                    console.print("[yellow]⚠ No Ollama models found. Recommendations:[/yellow]")
                    for m, ram, why in OLLAMA_RECOMMENDATIONS[:3]:
                        console.print(f"  • [cyan]{m}[/cyan] ({ram}) — {why}")
                    console.print(f"\n  Pull one with: [cyan]ollama pull qwen3:8b[/cyan]\n")
                llm_model = "qwen3:8b"
            else:
                rec = recommend_ollama_model(installed)
                if headless:
                    llm_model = rec
                else:
                    table = Table(title="Available Ollama Models", show_header=True, header_style="bold cyan")
                    table.add_column("#")
                    table.add_column("Model")
                    table.add_column("Notes")
                    for idx, m in enumerate(installed, start=1):
                        note = "← recommended" if m == rec else ""
                        table.add_row(str(idx), m, note)
                    console.print(table)
                    choice = Prompt.ask(
                        "[bold]4. Pick model[/bold] (number or name)",
                        default=rec,
                    )
                    if choice.isdigit():
                        idx = int(choice) - 1
                        if 0 <= idx < len(installed):
                            llm_model = installed[idx]
                        else:
                            llm_model = rec
                    else:
                        llm_model = choice

    # Estimates
    tokens_in, tokens_out, cost = estimate_tokens_and_cost(file_count_estimate, llm_model)
    seconds = estimate_seconds(file_count_estimate, llm_provider, parallel_workers)

    intent = ScanIntent(
        purpose=purpose,
        goal=goal,
        llm_provider=llm_provider,
        llm_model=llm_model,
        estimated_files=file_count_estimate,
        estimated_total_bytes=bytes_estimate,
        estimated_tokens_in=tokens_in,
        estimated_tokens_out=tokens_out,
        estimated_cost_usd=cost,
        estimated_seconds=seconds,
    )

    if not headless:
        _print_intent_summary(intent)

    return intent


def _print_intent_summary(intent: ScanIntent) -> None:
    """Show the user what's about to happen."""
    cost_str = "free (local)" if intent.estimated_cost_usd == 0 else f"${intent.estimated_cost_usd:.2f}"
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("[bold]Purpose[/bold]", intent.purpose)
    table.add_row("[bold]Goal[/bold]", intent.goal)
    table.add_row("[bold]LLM[/bold]", f"{intent.llm_provider}/{intent.llm_model}")
    table.add_row("[bold]Files[/bold]", f"~{intent.estimated_files:,}")
    table.add_row("[bold]Tokens in[/bold]", f"~{intent.estimated_tokens_in:,}")
    table.add_row("[bold]Tokens out[/bold]", f"~{intent.estimated_tokens_out:,}")
    table.add_row("[bold]Est. cost[/bold]", cost_str)
    table.add_row("[bold]Est. time[/bold]", _human_time(intent.estimated_seconds))
    console.print(Panel(table, title="Scan Intent", border_style="cyan"))


# --- Helpers ---

def _human_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    for unit, div in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)]:
        if b < div * 1024:
            return f"{b / div:.1f} {unit}"
    return f"{b / (1024**4):.1f} TB"


def _human_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
