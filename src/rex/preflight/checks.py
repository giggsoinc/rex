"""PreFlight checks — verify environment before scan.

All checks run in parallel where possible. Each check returns a CheckResult.
The overall PreFlightReport carries traffic-light status:
  - HARD_FAIL: cannot proceed (no disk, no Ollama, no destination)
  - SOFT_WARN: can proceed with degradation (no Gemini → no vision)
  - OK: green

User decides on SOFT_WARN unless intent.accept_soft_warnings=True.
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from rex.config import Settings, get_settings
from rex.preflight.checks_models import CheckResult, CheckStatus, PreFlightReport
from rex.preflight.checks_probes import (
    _noop_check,
    check_deps,
    check_disk,
    check_embed_model,
    check_gemini,
    check_lancedb_writable,
    check_ollama,
    check_source,
)
from rex.preflight.intent import ScanIntent

console = Console()
logger = structlog.get_logger()

__all__ = [
    "CheckStatus",
    "CheckResult",
    "PreFlightReport",
    "run_preflight",
    "print_preflight_report",
    "confirm_proceed",
]


# --- Runner ---

async def run_preflight(
    intent: ScanIntent,
    source_path: str,
    output_path: str,
    vector_path: str,
    settings: Settings | None = None,
) -> PreFlightReport:
    """Run all PreFlight checks in parallel."""
    s = settings or get_settings()

    tasks = [
        check_ollama(s, intent.llm_model) if intent.llm_provider == "ollama" else _noop_check("LLM", "Using cloud LLM"),
        check_embed_model(s),
        check_gemini(s),
        check_disk(source_path, output_path, intent.estimated_total_bytes),
        check_lancedb_writable(vector_path),
        check_source(source_path),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    results = list(results) + [check_deps()]

    report = PreFlightReport(results=results)
    report.compute_overall()
    return report


# --- UI ---

def print_preflight_report(report: PreFlightReport) -> None:
    """Render the PreFlight report as a table."""
    table = Table(title="PreFlight Report", show_header=True, header_style="bold")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details", overflow="fold")
    for r in report.results:
        if r.status == CheckStatus.OK:
            status_col = "[green]✓ OK[/green]"
        elif r.status == CheckStatus.SOFT_WARN:
            status_col = "[yellow]⚠ WARN[/yellow]"
        else:
            status_col = "[red]✗ FAIL[/red]"
        table.add_row(r.name, status_col, r.message)
    console.print(table)


def confirm_proceed(report: PreFlightReport, intent: ScanIntent) -> bool:
    """Ask user to proceed if SOFT_WARNs exist. Hard fail blocks unconditionally."""
    if report.overall == CheckStatus.HARD_FAIL:
        console.print(f"\n[red bold]✗ {len(report.hard_fails)} hard failure(s). Cannot proceed.[/red bold]")
        for r in report.hard_fails:
            console.print(f"  [red]• {r.name}:[/red] {r.message}")
            if r.detail.get("fix"):
                console.print(f"    [dim]Fix: {r.detail['fix']}[/dim]")
        return False

    if report.overall == CheckStatus.SOFT_WARN:
        if intent.accept_soft_warnings:
            console.print("\n[yellow]⚠ Soft warnings present — proceeding (--soft mode).[/yellow]")
            for r in report.soft_warns:
                console.print(f"  [yellow]• {r.name}:[/yellow] {r.message}")
            return True

        console.print(f"\n[yellow]⚠ {len(report.soft_warns)} soft warning(s):[/yellow]")
        for r in report.soft_warns:
            console.print(f"  • {r.name}: {r.message}")
            if r.detail.get("fix"):
                console.print(f"    [dim]Fix: {r.detail['fix']}[/dim]")
        if not sys.stdin.isatty():
            console.print("[dim]Non-interactive — defaulting to 'no'. Pass --soft to auto-accept.[/dim]")
            return False
        return Confirm.ask("\nProceed anyway?", default=True)

    return True
