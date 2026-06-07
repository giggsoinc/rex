"""Rex CLI main entry — dispatches subcommands.

Usage:
  rex init                  # onboarding wizard
  rex scan <folder>         # scan a folder (Phase 1)
  rex search <query>        # search organized files (Phase 1)
  rex status                # show current job status
"""

from __future__ import annotations

import sys

from rich.console import Console

console = Console()


def main() -> int:
    """Dispatch to the right subcommand."""
    if len(sys.argv) < 2:
        print_help()
        return 0

    cmd = sys.argv[1]

    if cmd == "init":
        from rex.cli.init import main as init_main
        return init_main()

    if cmd in {"-h", "--help", "help"}:
        print_help()
        return 0

    if cmd == "scan":
        from rex.cli.scan import main as scan_main
        return scan_main(sys.argv[2:])

    if cmd == "project":
        from rex.cli.project import main as project_main
        return project_main(sys.argv[2:])

    if cmd == "serve":
        from rex.cli.serve import main as serve_main
        return serve_main(sys.argv[2:])

    if cmd == "tail":
        from rex.cli.tail import main as tail_main
        return tail_main(sys.argv[2:])

    # Other commands stubs
    if cmd in {"search", "status"}:
        console.print(f"[yellow]'{cmd}' command coming next[/yellow]")
        return 0

    console.print(f"[red]Unknown command:[/red] {cmd}")
    print_help()
    return 1


def print_help() -> None:
    """Show usage."""
    console.print(
        "[bold cyan]Rex[/bold cyan] — Data Cleanup & Knowledge Management\n\n"
        "[bold]Commands:[/bold]\n"
        "  [cyan]rex init[/cyan]                  Onboarding wizard (pick deployment + vector store)\n"
        "  [cyan]rex project[/cyan] <cmd>         Manage projects (create/list/info/delete)\n"
        "  [cyan]rex scan[/cyan] <folder>         Scan and organize a folder (wizard unless --project)\n"
        "  [cyan]rex serve[/cyan]                 Start MCP server (stdio + HTTP)\n"
        "  [cyan]rex search[/cyan] <query>        Semantic search across organized files\n"
        "  [cyan]rex status[/cyan]                Show current job status\n"
        "  [cyan]rex tail[/cyan] [job_id]         Live-stream job progress (tail -f style)\n"
    )


if __name__ == "__main__":
    sys.exit(main())
