"""`rex project ...` — manage projects (create/list/info/delete)."""

from __future__ import annotations

import sys

from rich.console import Console

from rex.cli.project_cmds import cmd_create, cmd_delete, cmd_info, cmd_list

console = Console()


def main(argv: list[str] | None = None) -> int:
    """Dispatch project subcommands."""
    argv = argv or sys.argv[1:]
    if not argv:
        print_help()
        return 0

    sub = argv[0]
    rest = argv[1:]

    if sub == "create":
        return cmd_create(rest)
    if sub == "list":
        return cmd_list(rest)
    if sub == "info":
        return cmd_info(rest)
    if sub == "delete":
        return cmd_delete(rest)
    if sub in {"-h", "--help", "help"}:
        print_help()
        return 0

    console.print(f"[red]Unknown project subcommand:[/red] {sub}")
    print_help()
    return 1


def print_help() -> None:
    """Show usage."""
    console.print(
        "[bold cyan]rex project[/bold cyan] — manage Rex projects\n\n"
        "[bold]Commands:[/bold]\n"
        "  [cyan]rex project create <name>[/cyan]    Create a new project (with prompts)\n"
        "  [cyan]rex project list[/cyan]             List all projects\n"
        "  [cyan]rex project info <name>[/cyan]      Show project details\n"
        "  [cyan]rex project delete <name>[/cyan]    Delete a project metadata (use --purge to delete all data)\n"
    )
