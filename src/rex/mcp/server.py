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

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import structlog

from rex.config import get_settings
from rex.orchestrator.builder import build_project_pipeline
from rex.orchestrator.state import JobStore
from rex.projects.model import Project
from rex.projects.store import ProjectStore
from rex.vectorstore.lancedb_store import LanceDBStore

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

    # --- Project tools ---

    @app.tool()
    async def list_projects() -> dict[str, Any]:
        """List all Rex projects with name, context, vector store path, created time.

        Returns:
            {"projects": [{"name": str, "context": str, "vector_path": str,
                          "created_at": str, "default_source": str}, ...]}
        """
        store = ProjectStore()
        projects = store.list_all()
        return {
            "projects": [
                {
                    "name": p.name,
                    "context": p.context,
                    "vector_path": p.vector_path,
                    "output_path": p.output_path,
                    "default_source": p.default_source or "",
                    "created_at": p.created_at.isoformat(),
                }
                for p in projects
            ]
        }

    @app.tool()
    async def create_project(name: str, context: str = "", source: str = "") -> dict[str, Any]:
        """Create a new Rex project (isolated vector store + output + context).

        Args:
            name: Project name (lowercase, hyphens/underscores, max 64 chars).
            context: Free-text description (used as LLM router context).
            source: Optional default source folder path.

        Returns:
            Project metadata dict.
        """
        store = ProjectStore()
        try:
            project = store.create(name=name, context=context, default_source=source or None)
        except FileExistsError as e:
            return {"error": str(e)}
        return _project_dict(project)

    @app.tool()
    async def delete_project(name: str, purge: bool = False) -> dict[str, Any]:
        """Delete a project. If purge=True, also removes all data.

        Args:
            name: Project name.
            purge: If True, deletes vectors/jobs/output. Else removes metadata only.

        Returns:
            {"deleted": bool}
        """
        store = ProjectStore()
        ok = store.delete(name, also_remove_data=purge)
        return {"deleted": ok, "name": name, "purged": purge}

    # --- Scan + jobs ---

    @app.tool()
    async def scan(project: str, folder: str, job_name: str = "") -> dict[str, Any]:
        """Start a scan in a project. Runs scanner→router→organizer pipeline.

        Args:
            project: Name of project (must already exist; create_project first).
            folder: Source folder path to scan.
            job_name: Optional human-readable job name.

        Returns:
            Final ScanJob summary.
        """
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found. Create with create_project()."}

        src = Path(folder).expanduser().resolve()
        if not src.exists() or not src.is_dir():
            return {"error": f"Folder not found: {src}"}

        pipeline = build_project_pipeline(proj)
        job = await pipeline.run(str(src), output_path=proj.output_path, name=job_name or f"scan_{proj.name}")
        return {
            "job_id": job.id,
            "project": proj.name,
            "status": job.status.value,
            "scanned": job.scanned_files,
            "classified": job.classified_files,
            "organized": job.organized_files,
            "duplicates": job.duplicate_count,
            "categories": job.categories_discovered,
            "output_path": job.output_path,
            "catalog": f"{job.output_path}/_catalog/overview.md",
        }

    @app.tool()
    async def list_jobs(project: str) -> dict[str, Any]:
        """List all jobs for a project."""
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}
        jobs = await JobStore(base_path=proj.jobs_path).list_jobs()
        return {
            "jobs": [
                {
                    "id": j.id, "name": j.name, "status": j.status.value,
                    "scanned": j.scanned_files, "organized": j.organized_files,
                    "duplicates": j.duplicate_count,
                    "categories": j.categories_discovered,
                    "created_at": j.created_at.isoformat(),
                    "source_path": j.source_path,
                }
                for j in jobs
            ]
        }

    @app.tool()
    async def job_status(project: str, job_id: str) -> dict[str, Any]:
        """Get status of a specific job."""
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}
        job = await JobStore(base_path=proj.jobs_path).get_job(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found in project {project}"}
        return {
            "id": job.id, "name": job.name, "status": job.status.value,
            "scanned": job.scanned_files, "classified": job.classified_files,
            "organized": job.organized_files, "duplicates": job.duplicate_count,
            "categories": job.categories_discovered,
            "source_path": job.source_path, "output_path": job.output_path,
            "error": job.error,
        }

    # --- Search + retrieval ---

    @app.tool()
    async def search(project: str, query: str, top_k: int = 5) -> dict[str, Any]:
        """Semantic search across a project's indexed files.

        Args:
            project: Project name.
            query: Natural language query (will be embedded).
            top_k: Number of results to return.

        Returns:
            {"matches": [{"file_id", "score", "metadata"}, ...]}
        """
        from rex.ml.provider import ModelProvider

        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}

        settings = get_settings()
        model = ModelProvider(settings)
        vs = LanceDBStore(db_path=proj.vector_path, dim=settings.embed_dim)
        await vs.initialize()
        vec = await model.embed(query)
        matches = await vs.search(vec, top_k=top_k)
        return {
            "query": query,
            "matches": [
                {
                    "file_id": m.file_id,
                    "score": m.similarity_score,
                    "metadata": m.metadata,
                }
                for m in matches
            ],
        }

    @app.tool()
    async def get_file(project: str, file_id: str) -> dict[str, Any]:
        """Get full FileRecord (metadata + extracted text preview)."""
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}

        js = JobStore(base_path=proj.jobs_path)
        # Search all jobs for this file_id
        for job in await js.list_jobs():
            f = await js.get_file(job.id, file_id)
            if f is not None:
                return f.model_dump(mode="json", exclude_none=True)
        return {"error": f"File {file_id} not found in project {project}"}

    @app.tool()
    async def get_decision(project: str, file_id: str) -> dict[str, Any]:
        """Get the router's FileDecision for a file."""
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}

        js = JobStore(base_path=proj.jobs_path)
        for job in await js.list_jobs():
            d = await js.get_decision(job.id, file_id)
            if d is not None:
                return d.model_dump(mode="json", exclude_none=True)
        return {"error": f"Decision for file {file_id} not found"}

    @app.tool()
    async def get_catalog(project: str, doc: str = "overview") -> dict[str, Any]:
        """Get one of the catalog markdown files.

        Args:
            project: Project name.
            doc: One of: overview, index, categories, tags, duplicates.

        Returns:
            {"content": str, "path": str}
        """
        valid = {"overview", "index", "categories", "tags", "duplicates"}
        if doc not in valid:
            return {"error": f"doc must be one of {sorted(valid)}"}

        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}

        catalog = Path(proj.output_path) / "_catalog" / f"{doc}.md"
        if not catalog.exists():
            return {"error": f"Catalog not found at {catalog}. Run a scan first."}
        return {"content": catalog.read_text(), "path": str(catalog)}

    @app.tool()
    async def get_duplicates(project: str, job_id: str = "") -> dict[str, Any]:
        """Get duplicate groups for a job (or latest job if job_id omitted)."""
        store = ProjectStore()
        proj = store.load(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}

        js = JobStore(base_path=proj.jobs_path)
        if not job_id:
            jobs = await js.list_jobs()
            if not jobs:
                return {"error": "No jobs in project"}
            job_id = jobs[0].id

        files = await js.list_files(job_id)
        decisions = await js.list_decisions(job_id)
        file_by_id = {f.id: f for f in files}

        groups: dict[str, list[dict]] = {}
        for f in files:
            d = decisions.get(f.id)
            if not d or not d.duplicate_of:
                continue
            original = file_by_id.get(d.duplicate_of)
            original_name = original.filename if original else d.duplicate_of
            groups.setdefault(original_name, []).append({
                "filename": f.filename,
                "dedup_status": d.dedup_status.value,
                "original_path": f.original_path,
            })

        return {"job_id": job_id, "duplicate_groups": groups, "count": sum(len(v) for v in groups.values())}

    return app


def _project_dict(p: Project) -> dict[str, Any]:
    """Project serialization for MCP responses."""
    return {
        "name": p.name,
        "context": p.context,
        "root_path": p.root_path,
        "vector_path": p.vector_path,
        "jobs_path": p.jobs_path,
        "output_path": p.output_path,
        "default_source": p.default_source or "",
        "created_at": p.created_at.isoformat(),
    }


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
