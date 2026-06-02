"""UI helpers for the intent dialog — Ollama model resolution + summary."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from rex.preflight.intent_estimate import (
    OLLAMA_RECOMMENDATIONS,
    list_available_ollama_models,
    recommend_ollama_model,
)
from rex.preflight.intent_model import ScanIntent

console = Console()


def resolve_ollama_model(llm_model: str | None, headless: bool) -> str:
    """Resolve the Ollama model to use, prompting interactively when possible."""
    from rich.prompt import Prompt

    installed = list_available_ollama_models()
    if llm_model and llm_model in installed:
        return llm_model

    if not installed:
        if not headless:
            console.print("[yellow]⚠ No Ollama models found. Recommendations:[/yellow]")
            for m, ram, why in OLLAMA_RECOMMENDATIONS[:3]:
                console.print(f"  • [cyan]{m}[/cyan] ({ram}) — {why}")
            console.print(f"\n  Pull one with: [cyan]ollama pull qwen3:8b[/cyan]\n")
        return "qwen3:8b"

    rec = recommend_ollama_model(installed)
    if headless:
        return rec

    table = Table(title="Available Ollama Models", show_header=True, header_style="bold cyan")
    table.add_column("#")
    table.add_column("Model")
    table.add_column("Notes")
    for idx, m in enumerate(installed, start=1):
        note = "← recommended" if m == rec else ""
        table.add_row(str(idx), m, note)
    console.print(table)
    choice = Prompt.ask("[bold]4. Pick model[/bold] (number or name)", default=rec)
    if choice.isdigit():
        idx = int(choice) - 1
        return installed[idx] if 0 <= idx < len(installed) else rec
    return choice


def print_intent_summary(intent: ScanIntent) -> None:
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
    table.add_row("[bold]Est. time[/bold]", human_time(intent.estimated_seconds))
    console.print(Panel(table, title="Scan Intent", border_style="cyan"))


def human_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    for unit, div in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)]:
        if b < div * 1024:
            return f"{b / div:.1f} {unit}"
    return f"{b / (1024**4):.1f} TB"


def human_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
