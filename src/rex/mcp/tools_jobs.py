"""Scan + job MCP tools: scan, list_jobs, job_status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rex.orchestrator.builder import build_project_pipeline
from rex.orchestrator.state import JobStore
from rex.projects.store import ProjectStore


def register_job_tools(app) -> None:
    """Register scan and job tools on the FastMCP app."""

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
