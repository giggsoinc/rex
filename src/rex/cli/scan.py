"""`rex scan <folder>` — the full Rex flow.

Every scan now runs:
  Intent dialog → PreFlight checks → Planner → Coordinator → Workers → Janitor

User can override prompts with flags. Flow is project-isolated and parallel.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

from rex.config import get_settings
from rex.coordinator import get_coordinator
from rex.janitor import Janitor
from rex.planner import Planner
from rex.preflight import gather_intent, run_preflight
from rex.preflight.checks import (
    CheckStatus,
    confirm_proceed,
    print_preflight_report,
)
from rex.projects.model import Project
from rex.projects.store import ProjectStore

console = Console()


def main(argv: list[str] | None = None) -> int:
    """`rex scan <folder> [--project NAME] [--workers N] [--mode asyncio|mp] [--soft] [-y]`"""
    argv = argv or sys.argv[1:]
    if not argv:
        console.print("[red]Usage:[/red] rex scan <folder> [--project <name>] [--workers N] [--mode asyncio|mp] [--soft]")
        return 1

    source = argv[0]
    project_name: str | None = None
    workers = 4
    mode = "asyncio"
    soft = False
    yes = False

    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--project" and i + 1 < len(argv):
            project_name = argv[i + 1]; i += 2
        elif a == "--workers" and i + 1 < len(argv):
            workers = int(argv[i + 1]); i += 2
        elif a == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]; i += 2
        elif a == "--soft":
            soft = True; i += 1
        elif a in {"-y", "--yes"}:
            yes = True; i += 1
        else:
            i += 1

    src_path = Path(source).expanduser().resolve()
    if not src_path.exists() or not src_path.is_dir():
        console.print(f"[red]Source folder not found:[/red] {src_path}")
        return 2

    store = ProjectStore()

    # Project resolution
    project: Project | None = None
    if project_name:
        project = store.load(project_name)
        if project is None:
            console.print(f"[red]Project '{project_name}' not found.[/red] Create with: rex project create {project_name}")
            return 3
    if project is None:
        project = _run_project_wizard(src_path, store)
        if project is None:
            return 0

    return asyncio.run(_run(src_path, project, workers, mode, soft, yes))


def _run_project_wizard(src_path: Path, store: ProjectStore) -> Project | None:
    """Pick existing project or create new (forced wizard)."""
    projects = store.list_all()
    if projects:
        console.print("\n[bold]Existing projects:[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#"); table.add_column("Name"); table.add_column("Context", overflow="fold")
        for idx, p in enumerate(projects, start=1):
            ctx = (p.context[:60] + "…") if len(p.context) > 60 else p.context
            table.add_row(str(idx), p.name, ctx or "(none)")
        console.print(table)
        choices = [str(i) for i in range(1, len(projects) + 1)] + ["n", "new"]
        choice = Prompt.ask("Select project [#] or [n] for new", choices=choices, default="n", show_choices=False)
        if choice not in {"n", "new"}:
            return projects[int(choice) - 1]

    import re
    name = Prompt.ask("Project name (lowercase, hyphens/underscores)", default=src_path.name.lower().replace(" ", "-"))
    name = re.sub(r"[^a-z0-9_-]", "-", name.lower())
    name = re.sub(r"-+", "-", name).strip("-_") or "default"
    context = Prompt.ask("Project context (what kind of files / what's it for?)", default=f"Files from {src_path.name}")
    if store.exists(name):
        return store.load(name) if Confirm.ask(f"Project '{name}' exists. Use it?", default=True) else None
    return store.create(name=name, context=context, default_source=str(src_path))


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


async def _quick_count(source: str) -> tuple[int, int]:
    """Fast file count + size estimate without classifying."""
    from rex.utils.skip_rules import SkipRules, is_skip_dir, should_skip, SkipReason
    import os

    rules = SkipRules.default()

    def _count():
        count = 0
        total = 0
        for dirpath, dirnames, filenames in os.walk(source):
            dirnames[:] = [d for d in dirnames if not is_skip_dir(d, rules)]
            for fn in filenames:
                fp = Path(dirpath) / fn
                if should_skip(fp, rules) != SkipReason.NONE:
                    continue
                try:
                    total += fp.stat().st_size
                    count += 1
                except OSError:
                    pass
        return count, total

    return await asyncio.to_thread(_count)


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
