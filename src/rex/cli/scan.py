"""`rex scan <folder>` — the full Rex flow.

Every scan now runs:
  Intent dialog → PreFlight checks → Planner → Coordinator → Workers → Janitor

User can override prompts with flags. Flow is project-isolated and parallel.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console

from rex.cli.scan_flow import _run
from rex.cli.scan_wizard import _run_project_wizard
from rex.projects.model import Project
from rex.projects.store import ProjectStore

console = Console()


def main(argv: list[str] | None = None) -> int:
    """`rex scan <folder> [--project NAME] [--output PATH] [--workers N] [--mode asyncio|mp] [--soft] [-y]`"""
    argv = argv or sys.argv[1:]
    if not argv:
        console.print(
            "[red]Usage:[/red] rex scan <folder> [--project <name>] "
            "[--output <path>] [--workers N] [--mode asyncio|mp] [--soft] [--bg]"
        )
        return 1

    source = argv[0]
    project_name: str | None = None
    output_override: str | None = None
    workers = 4
    mode = "asyncio"
    soft = False
    yes = False
    bg = False

    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--project" and i + 1 < len(argv):
            project_name = argv[i + 1]; i += 2
        elif a == "--output" and i + 1 < len(argv):
            output_override = argv[i + 1]; i += 2
        elif a == "--workers" and i + 1 < len(argv):
            workers = int(argv[i + 1]); i += 2
        elif a == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]; i += 2
        elif a == "--soft":
            soft = True; i += 1
        elif a in {"-y", "--yes"}:
            yes = True; i += 1
        elif a == "--bg":
            bg = True; i += 1
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

    if bg:
        from rex.cli.scan_submit import submit_background
        return submit_background(
            src_path, project, workers=workers, mode=mode,
            soft=soft, output_override=output_override,
        )

    return asyncio.run(_run(src_path, project, workers, mode, soft, yes, output_override))
