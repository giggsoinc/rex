"""Interactive intent-gathering dialog."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from rex.config import get_settings
from rex.preflight.intent_dialog_ui import (
    human_size,
    print_intent_summary,
    resolve_ollama_model,
)
from rex.preflight.intent_estimate import estimate_seconds, estimate_tokens_and_cost
from rex.preflight.intent_model import ScanIntent

console = Console()


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
                      f"~{human_size(bytes_estimate)}")
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
        llm_model = resolve_ollama_model(llm_model, headless)

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
        print_intent_summary(intent)

    return intent
