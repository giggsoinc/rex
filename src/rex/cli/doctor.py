"""`rex doctor` — system + Python health check for Rex.

Runs all checks from doctor_checks.ALL_CHECKS and prints a colored table
with green / amber / red status + remediation. Exits non-zero on red
(or any non-green in --strict mode) for CI-friendly health validation.

Usage:
    rex doctor                # full check
    rex doctor --strict       # exit non-zero on any non-green
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from rex.cli.doctor_checks import ALL_CHECKS

console = Console()

__all__ = ["main"]

_STYLE = {
    "green": "[bold green]✅ green[/bold green]",
    "amber": "[bold yellow]⚠️  amber[/bold yellow]",
    "red":   "[bold red]❌ red[/bold red]",
}


def main(argv: list[str]) -> int:
    """Run all checks, print a table, exit non-zero on red (or strict amber)."""
    strict = "--strict" in argv
    console.print("[bold cyan]Rex Doctor — health check[/bold cyan]\n")

    results = [check() for check in ALL_CHECKS]
    table = Table(show_lines=False, header_style="bold")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("Detail")
    for r in results:
        table.add_row(r.name, _STYLE[r.status], r.detail)
    console.print(table)

    fixes = [r for r in results if r.status != "green" and r.fix]
    if fixes:
        console.print("\n[bold]How to fix:[/bold]")
        for r in fixes:
            icon = "⚠️" if r.status == "amber" else "❌"
            console.print(f"\n{icon} [bold]{r.name}[/bold]\n   {r.fix}")
    else:
        console.print("\n[bold green]All systems go.[/bold green] Run `rex scan <folder>`.")

    has_red = any(r.status == "red" for r in results)
    has_amber = any(r.status == "amber" for r in results)
    if has_red:
        return 2
    if strict and has_amber:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
