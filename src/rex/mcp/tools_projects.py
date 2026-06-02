"""Project-management MCP tools: list_projects, create_project, delete_project."""

from __future__ import annotations

from typing import Any

from rex.projects.model import Project
from rex.projects.store import ProjectStore


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


def register_project_tools(app) -> None:
    """Register project-management tools on the FastMCP app."""

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
