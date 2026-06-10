"""Scan + job MCP tools: scan (live progress), scan_start (background), status.

Two ways to scan over MCP:
  scan        — blocking, streams MCP progress notifications while it runs
                (progress resets the client timeout per MCP spec). Good for
                small/medium folders.
  scan_start  — returns job_id IMMEDIATELY; pipeline runs as a background
                asyncio task. Poll job_status(project, job_id) for live
                heartbeat (scanned/classified/organized + current_file).
                The right choice for big folders.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from fastmcp import Context

from rex.orchestrator.builder import build_project_pipeline
from rex.orchestrator.state import JobStore
from rex.projects.store import ProjectStore

logger = structlog.get_logger()

# Keep strong refs so background scans aren't garbage-collected mid-run.
_BACKGROUND: dict[str, asyncio.Task] = {}


def _load_project(name: str):
    """Load a project or return (None, error-dict)."""
    proj = ProjectStore().load(name)
    if proj is None:
        return None, {"error": f"Project '{name}' not found. Create with create_project()."}
    return proj, None


def _job_summary(job) -> dict[str, Any]:
    """Uniform job → dict for tool responses."""
    return {
        "job_id": job.id, "name": job.name, "status": job.status.value,
        "scanned": job.scanned_files, "classified": job.classified_files,
        "organized": job.organized_files, "duplicates": job.duplicate_count,
        "categories": job.categories_discovered,
        "current_file": job.current_file,
        "last_progress_at": job.last_progress_at.isoformat() if job.last_progress_at else None,
        "output_path": job.output_path, "error": job.error,
    }


def register_job_tools(app) -> None:
    """Register scan / scan_start / list_jobs / job_status on the FastMCP app."""

    @app.tool()
    async def scan(project: str, folder: str, job_name: str = "", ctx: Context = None) -> dict[str, Any]:
        """Scan a folder (BLOCKING, with live progress notifications).

        Streams MCP progress while running — each file advances the bar and
        resets the client timeout. For folders over ~500 files prefer
        scan_start() + job_status() polling instead.
        """
        proj, err = _load_project(project)
        if err:
            return err
        src = Path(folder).expanduser().resolve()
        if not src.is_dir():
            return {"error": f"Folder not found: {src}"}

        pipeline = build_project_pipeline(proj)
        if ctx is not None:
            async def on_progress(p) -> None:
                done = max(p.organized, p.routed, p.scanned)
                await ctx.report_progress(
                    progress=done, total=max(p.total, 1),
                    message=f"{p.status.value} · {(p.current_file or '')[:60]}",
                )
            pipeline.on_progress = on_progress

        job = await pipeline.run(str(src), output_path=proj.output_path,
                                 name=job_name or f"scan_{proj.name}")
        return _job_summary(job)

    @app.tool()
    async def scan_start(project: str, folder: str, job_name: str = "") -> dict[str, Any]:
        """Start a scan in the BACKGROUND — returns job_id immediately.

        The pipeline keeps running inside the MCP server process. Poll
        job_status(project, job_id) for live counters + heartbeat. Safe for
        large folders (no client timeout exposure).
        """
        proj, err = _load_project(project)
        if err:
            return err
        src = Path(folder).expanduser().resolve()
        if not src.is_dir():
            return {"error": f"Folder not found: {src}"}

        job_id = JobStore.compute_job_id(str(src))
        if (t := _BACKGROUND.get(job_id)) and not t.done():
            return {"job_id": job_id, "status": "already_running",
                    "poll": f"job_status('{project}', '{job_id}')"}

        pipeline = build_project_pipeline(proj)
        task = asyncio.create_task(
            pipeline.run(str(src), output_path=proj.output_path,
                         name=job_name or f"scan_{proj.name}")
        )
        _BACKGROUND[job_id] = task

        def _done(t: asyncio.Task) -> None:
            _BACKGROUND.pop(job_id, None)
            if not t.cancelled() and (exc := t.exception()):
                # pipeline.run already wrote FAILED to job.json; this avoids
                # "exception was never retrieved" noise.
                logger.error("background_scan_failed", job_id=job_id, error=str(exc)[:200])
        task.add_done_callback(_done)

        return {"job_id": job_id, "status": "started", "source": str(src),
                "output_path": proj.output_path,
                "poll": f"job_status('{project}', '{job_id}')"}

    @app.tool()
    async def list_jobs(project: str) -> dict[str, Any]:
        """List all jobs for a project (most recent first)."""
        proj, err = _load_project(project)
        if err:
            return err
        jobs = await JobStore(base_path=proj.jobs_path).list_jobs()
        return {"jobs": [_job_summary(j) | {"source_path": j.source_path,
                                            "created_at": j.created_at.isoformat()}
                         for j in jobs]}

    @app.tool()
    async def job_status(project: str, job_id: str) -> dict[str, Any]:
        """Get live status of a job — counters, current_file, heartbeat."""
        proj, err = _load_project(project)
        if err:
            return err
        job = await JobStore(base_path=proj.jobs_path).get_job(job_id)
        if job is None:
            return {"error": f"Job {job_id} not found in project {project}"}
        running = (t := _BACKGROUND.get(job_id)) is not None and not t.done()
        return _job_summary(job) | {"background_task_alive": running,
                                    "source_path": job.source_path}
