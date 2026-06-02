"""Query + retrieval MCP tools: search, get_file, get_decision, get_catalog, get_duplicates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rex.config import get_settings
from rex.orchestrator.state import JobStore
from rex.projects.store import ProjectStore
from rex.vectorstore.lancedb_store import LanceDBStore


def register_query_tools(app) -> None:
    """Register search and retrieval tools on the FastMCP app."""

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
