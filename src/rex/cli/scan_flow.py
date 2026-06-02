"""The full `rex scan` execution flow: preflight → plan → coordinate → janitor."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from rex.cli.scan_ui import _print_final_summary, _print_plan_summary
from rex.cli.scan_wizard import _quick_count
from rex.config import get_settings
from rex.coordinator import get_coordinator
from rex.janitor import Janitor
from rex.planner import Planner
from rex.preflight import gather_intent, run_preflight
from rex.preflight.checks import confirm_proceed, print_preflight_report
from rex.projects.model import Project

console = Console()


async def _run(src_path: Path, project: Project, workers: int, mode: str, soft: bool, yes: bool) -> int:
    """The full scan flow."""
    settings = get_settings()

    # 1. Quick file count for intent dialog
    file_count, total_bytes = await _quick_count(str(src_path))

    # 2. Intent dialog (every run)
    intent = gather_intent(
        source_path=str(src_path),
        file_count_estimate=file_count,
        bytes_estimate=total_bytes,
        parallel_workers=workers,
    )
    intent.accept_soft_warnings = soft

    # 3. PreFlight checks
    console.print("\n[bold cyan]Running PreFlight…[/bold cyan]")
    report = await run_preflight(
        intent=intent,
        source_path=str(src_path),
        output_path=project.output_path,
        vector_path=project.vector_path,
        settings=settings,
    )
    print_preflight_report(report)
    if not confirm_proceed(report, intent):
        return 4

    # 4. Plan (fast, no LLM)
    console.print("\n[bold cyan]Planning…[/bold cyan]")
    planner = Planner(target_batch_count=workers)
    plan = await planner.plan(str(src_path), project.name)

    _print_plan_summary(plan)
    if not yes and sys.stdin.isatty():
        if not Confirm.ask("\nProceed with this plan?", default=True):
            console.print("[yellow]Aborted.[/yellow]")
            return 0

    # 5. Coordinator — execute batches in parallel
    coordinator = get_coordinator(mode)
    console.print(f"\n[bold cyan]Executing with {coordinator.name()} ({workers} workers)…[/bold cyan]")

    # Wire SIGINT to janitor on_kill
    janitor = Janitor(settings)
    kill_handled = asyncio.Event()

    def _kill_handler(signum, frame):
        if not kill_handled.is_set():
            kill_handled.set()
            console.print("\n[yellow]Kill signal received — janitor will clean up after current batches[/yellow]")
    signal.signal(signal.SIGINT, _kill_handler)

    try:
        result = await coordinator.run_plan(plan, project, intent, max_concurrency=workers)
    except Exception as e:
        console.print(f"[red]Coordinator failed:[/red] {e}")
        await janitor.on_crash(project, plan.id, error=str(e))
        return 5

    # 6. Janitor — merge shards + finalize catalog
    console.print("\n[bold cyan]Janitor cleanup…[/bold cyan]")
    if kill_handled.is_set():
        jres = await janitor.on_kill(project, plan.id)
    else:
        jres = await janitor.on_complete(project, plan.id)

    _print_final_summary(project, plan, result, jres)
    return 0
