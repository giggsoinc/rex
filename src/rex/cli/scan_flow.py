"""The full `rex scan` execution flow: preflight → plan → coordinate → janitor."""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from rex.cli.scan_ui import _print_final_summary, _print_plan_summary
from rex.cli.scan_wizard import _quick_count
from rex.config import get_settings
from rex.coordinator import get_coordinator
from rex.janitor import Janitor
from rex.orchestrator.job_control import (
    CancelFileWatcher,
    clear_cancel,
    job_dir_for,
    write_pid,
)
from rex.planner import Planner
from rex.preflight import gather_intent, run_preflight
from rex.preflight.checks import confirm_proceed, print_preflight_report
from rex.projects.model import Project

console = Console()


async def _run(
    src_path: Path, project: Project, workers: int, mode: str,
    soft: bool, yes: bool, output_override: str | None = None,
) -> int:
    """The full scan flow.

    If output_override is provided, it replaces project.output_path for this
    run AND is stamped onto the project (so downstream stages — coordinator,
    janitor, preflight — all see the same path).
    """
    settings = get_settings()

    # Apply output override before any stage reads project.output_path
    if output_override:
        resolved = str(Path(output_override).expanduser().resolve())
        console.print(
            f"[cyan]Output path override:[/cyan] {project.output_path} → {resolved}"
        )
        project.output_path = resolved
        Path(resolved).mkdir(parents=True, exist_ok=True)

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

    # Wire SIGINT: first Ctrl+C drains gracefully, second force-quits
    janitor = Janitor(settings)
    cancel_event = threading.Event()
    prev_handler = signal.getsignal(signal.SIGINT)

    # Cross-process kill: UI/`rex jobs kill` touch <job_dir>/CANCEL
    job_dir = job_dir_for(project.jobs_path, str(src_path))
    clear_cancel(job_dir)
    write_pid(job_dir)
    watcher = CancelFileWatcher(job_dir, cancel_event)
    watcher.start()

    def _kill_handler(signum, frame):
        if not cancel_event.is_set():
            cancel_event.set()
            console.print(
                "\n[yellow]Ctrl+C — finishing in-flight batches, skipping the rest. "
                "Press Ctrl+C again to force quit.[/yellow]"
            )
        else:
            signal.signal(signal.SIGINT, prev_handler)
            raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _kill_handler)

    try:
        result = await coordinator.run_plan(
            plan, project, intent, max_concurrency=workers, cancel_event=cancel_event,
        )
    except KeyboardInterrupt:
        import os
        console.print("[red]Force quit — checkpointing what we can…[/red]")
        await janitor.on_kill(project, plan.id)
        # os._exit skips the ProcessPoolExecutor atexit join that would
        # otherwise block exit until every child finishes its batch.
        os._exit(130)
    except Exception as e:
        console.print(f"[red]Coordinator failed:[/red] {e}")
        await janitor.on_crash(project, plan.id, error=str(e))
        return 5
    finally:
        signal.signal(signal.SIGINT, prev_handler)
        watcher.stop()
        clear_cancel(job_dir)
        (job_dir / "pid").unlink(missing_ok=True)

    # 6. Janitor — merge shards + finalize catalog
    console.print("\n[bold cyan]Janitor cleanup…[/bold cyan]")
    if cancel_event.is_set():
        jres = await janitor.on_kill(project, plan.id)
    else:
        jres = await janitor.on_complete(project, plan.id)

    _print_final_summary(project, plan, result, jres)
    return 0
