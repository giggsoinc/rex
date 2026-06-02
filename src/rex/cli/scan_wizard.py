"""Project selection wizard + fast file counter for `rex scan`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from rex.projects.model import Project
from rex.projects.store import ProjectStore

console = Console()


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
