"""`rex serve` — start the MCP server.

Modes:
  rex serve                     stdio + HTTP (default)
  rex serve --stdio             stdio only
  rex serve --http              HTTP only
  rex serve --port 8765         set HTTP port
  rex serve --host 0.0.0.0      bind interface
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel

# Route ALL human-facing output to stderr — stdout must stay pure JSON-RPC
# for the stdio MCP transport (banners on stdout corrupt the protocol stream).
console = Console(stderr=True)


def main(argv: list[str] | None = None) -> int:
    """Start the MCP server with chosen transport(s)."""
    argv = argv or sys.argv[1:]

    stdio_only = "--stdio" in argv
    http_only = "--http" in argv
    host = "127.0.0.1"
    port = 8765

    i = 0
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]; i += 2
        elif argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1]); i += 2
        else:
            i += 1

    try:
        from rex.mcp.server import run_both, run_http, run_stdio
    except ImportError as e:
        console.print(f"[red]MCP server unavailable:[/red] {e}")
        console.print("Install with: [cyan]pip install fastmcp[/cyan]")
        return 1

    if stdio_only and http_only:
        console.print("[red]--stdio and --http are mutually exclusive (default is both)[/red]")
        return 1

    if stdio_only:
        console.print("[cyan]Rex MCP — stdio only[/cyan]")
        run_stdio()
        return 0

    if http_only:
        _banner("HTTP", host, port)
        run_http(host=host, port=port)
        return 0

    # Default: both
    _banner("stdio + HTTP", host, port)
    run_both(host=host, port=port)
    return 0


def _banner(mode: str, host: str, port: int) -> None:
    """Print server-ready banner."""
    console.print(Panel.fit(
        f"[bold cyan]Rex MCP Server[/bold cyan]\n"
        f"Mode:  {mode}\n"
        f"HTTP:  [cyan]http://{host}:{port}[/cyan]\n"
        f"Stdio: ready for MCP client (Claude Desktop / Cursor)",
        border_style="cyan",
    ))
