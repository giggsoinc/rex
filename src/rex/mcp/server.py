"""Rex MCP server — exposes Rex as MCP tools for any MCP client.

Built on FastMCP. Supports both stdio (Claude Desktop, Cursor) and HTTP
(Perplexity, Manus, browser tools) transports.

Tools exposed:
  list_projects()
  create_project(name, context, source?)
  delete_project(name, purge=False)
  scan(project, folder, job_name?)
  job_status(project, job_id)
  list_jobs(project)
  search(project, query, top_k=5)
  get_file(project, file_id)
  get_decision(project, file_id)
  get_catalog(project, job_id, doc='overview')
  get_duplicates(project, job_id)
"""

from __future__ import annotations

import structlog

from rex.mcp.tools_jobs import register_job_tools
from rex.mcp.tools_projects import _project_dict, register_project_tools
from rex.mcp.tools_query import register_query_tools

__all__ = [
    "build_mcp_app",
    "run_stdio",
    "run_http",
    "run_both",
    "_project_dict",
]

logger = structlog.get_logger()


def build_mcp_app():
    """Construct the FastMCP application with all Rex tools."""
    try:
        from fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(
            "fastmcp is required for `rex serve`. Install with: pip install fastmcp"
        ) from e

    app = FastMCP("rex", version="0.1.0")
    register_project_tools(app)
    register_job_tools(app)
    register_query_tools(app)
    return app


# --- Entry points for stdio / http ---

def run_stdio() -> None:
    """Run as stdio MCP server (Claude Desktop, Cursor)."""
    app = build_mcp_app()
    app.run()  # FastMCP defaults to stdio


def run_http(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run as HTTP MCP server (Perplexity, Manus, browser tools)."""
    app = build_mcp_app()
    # FastMCP 2.x supports streamable-http transport
    try:
        app.run(transport="http", host=host, port=port)
    except TypeError:
        # Older FastMCP signature
        app.run(transport="sse", host=host, port=port)


def run_both(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run stdio and HTTP in parallel.

    HTTP is started in a background thread; stdio runs in the main thread.
    Useful for development — one process serves Claude Desktop AND a web client.
    """
    import threading

    def _http():
        try:
            run_http(host=host, port=port)
        except Exception as e:
            logger.error("mcp_http_server_failed", error=str(e))

    t = threading.Thread(target=_http, name="rex-mcp-http", daemon=True)
    t.start()
    logger.info("mcp_http_started", host=host, port=port)
    run_stdio()
