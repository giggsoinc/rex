"""Rendering helpers for `rex scan` — plan/summary tables and humanizers."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _print_plan_summary(plan) -> None:
    """Show plan summary."""
    table = Table(title="Scan Plan", show_header=True, header_style="bold cyan")
    table.add_column("Metric"); table.add_column("Value")
    table.add_row("Total files", f"{plan.total_files:,}")
    table.add_row("Total size", _human_size(plan.total_bytes))
    table.add_row("Batches", str(plan.batch_count))
    table.add_row("Skipped", str(len(plan.skipped)))
    table.add_row("Est. time (parallel)", _human_time(plan.estimated_seconds))
    console.print(table)

    if plan.files_by_type:
        type_table = Table(title="Files by type", show_header=True, header_style="bold")
        type_table.add_column("Type"); type_table.add_column("Count")
        for t, c in sorted(plan.files_by_type.items(), key=lambda x: -x[1]):
            type_table.add_row(t, str(c))
        console.print(type_table)

    if plan.skipped:
        console.print(f"\n[dim]Skipped {len(plan.skipped)} files.[/dim] Run [cyan]rex plan show {plan.id}[/cyan] for details.")


def _print_final_summary(project, plan, result, janitor_result) -> None:
    """Show summary panel."""
    cost = janitor_result.get("merged_rows", 0)
    msg = (
        f"[bold green]✓ Scan complete[/bold green]\n\n"
        f"Project:    [cyan]{project.name}[/cyan]\n"
        f"Plan:       [cyan]{plan.id}[/cyan]\n"
        f"Batches:    {result.completed}/{result.total_batches} ok, {result.failed} failed\n"
        f"Files:      {result.files_processed}\n"
        f"Vectors:    {cost} merged from {plan.batch_count} shards\n"
        f"Output:     [cyan]{project.output_path}[/cyan]\n"
        f"Catalog:    [cyan]{project.output_path}/_catalog/overview.md[/cyan]"
    )
    console.print(Panel(msg, border_style="green"))


def _human_size(b: int) -> str:
    if b < 1024: return f"{b} B"
    for unit, div in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)]:
        if b < div * 1024:
            return f"{b / div:.1f} {unit}"
    return f"{b / (1024**4):.1f} TB"


def _human_time(s: int) -> str:
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"
