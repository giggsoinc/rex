"""`rex project` subcommand implementations (create/list/info/delete)."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from rex.projects.model import Project
from rex.projects.store import ProjectStore

console = Console()


def cmd_create(argv: list[str]) -> int:
    """`rex project create <name> [--context ...] [--source ...]`"""
    if not argv:
        console.print("[red]Usage:[/red] rex project create <name> [--context <text>] [--source <folder>]")
        return 1

    name = argv[0]
    context = ""
    source: str | None = None
    overwrite = False

    i = 1
    while i < len(argv):
        if argv[i] == "--context" and i + 1 < len(argv):
            context = argv[i + 1]; i += 2
        elif argv[i] == "--source" and i + 1 < len(argv):
            source = argv[i + 1]; i += 2
        elif argv[i] == "--overwrite":
            overwrite = True; i += 1
        else:
            i += 1

    # Interactive context only if stdin is a TTY (otherwise skip prompts)
    if not context and sys.stdin.isatty():
        context = Prompt.ask(
            "[bold]Project context[/bold] (one-liner describing what's in this project)",
            default="",
        )
    if not source and sys.stdin.isatty():
        ans = Prompt.ask("Default source folder (optional, blank to skip)", default="")
        source = ans if ans else None

    store = ProjectStore()
    try:
        project = store.create(name=name, context=context, default_source=source, overwrite=overwrite)
    except FileExistsError as e:
        console.print(f"[red]✗[/red] {e}")
        return 2

    _print_project_panel(project, title=f"✓ Project '{name}' created")
    console.print(f"\n[dim]Next:[/dim] [cyan]rex scan <folder> --project {name}[/cyan]")
    return 0


def cmd_list(_: list[str]) -> int:
    """`rex project list`"""
    store = ProjectStore()
    projects = store.list_all()

    if not projects:
        console.print("[yellow]No projects yet.[/yellow]")
        console.print("Create one with: [cyan]rex project create <name>[/cyan]")
        return 0

    table = Table(title="Rex Projects", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Created (UTC)", style="dim")
    table.add_column("Context", overflow="fold")
    table.add_column("Vector store", style="dim", overflow="fold")
    for p in projects:
        table.add_row(
            p.name,
            p.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            (p.context[:80] + "…") if len(p.context) > 80 else p.context,
            Path(p.vector_path).name,
        )
    console.print(table)
    return 0


def cmd_info(argv: list[str]) -> int:
    """`rex project info <name>`"""
    if not argv:
        console.print("[red]Usage:[/red] rex project info <name>")
        return 1
    name = argv[0]
    store = ProjectStore()
    project = store.load(name)
    if project is None:
        console.print(f"[red]Project not found:[/red] {name}")
        return 2
    _print_project_panel(project, title=f"Project: {name}")
    return 0


def cmd_delete(argv: list[str]) -> int:
    """`rex project delete <name> [--purge]`"""
    if not argv:
        console.print("[red]Usage:[/red] rex project delete <name> [--purge]")
        return 1
    name = argv[0]
    purge = "--purge" in argv

    store = ProjectStore()
    project = store.load(name)
    if project is None:
        console.print(f"[red]Project not found:[/red] {name}")
        return 2

    word = "PURGE ALL DATA" if purge else "remove metadata only"
    if not Confirm.ask(f"[bold red]Delete '{name}' — {word}?[/bold red]", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return 0

    store.delete(name, also_remove_data=purge)
    console.print(f"[green]✓[/green] Deleted '{name}' ({word})")
    return 0


def _print_project_panel(project: Project, title: str) -> None:
    """Pretty-print a project."""
    body = (
        f"[bold]Name:[/bold]      {project.name}\n"
        f"[bold]Created:[/bold]   {project.created_at} UTC\n"
        f"[bold]Context:[/bold]   {project.context or '(none)'}\n"
        f"[bold]Source:[/bold]    {project.default_source or '(none)'}\n\n"
        f"[bold]Root:[/bold]      [cyan]{project.root_path}[/cyan]\n"
        f"[bold]Vector DB:[/bold] [cyan]{project.vector_path}[/cyan]\n"
        f"[bold]Jobs:[/bold]      [cyan]{project.jobs_path}[/cyan]\n"
        f"[bold]Output:[/bold]    [cyan]{project.output_path}[/cyan]"
    )
    console.print(Panel(body, title=title, border_style="cyan"))
