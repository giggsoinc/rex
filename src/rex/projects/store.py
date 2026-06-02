"""ProjectStore — CRUD over ~/rex-data/projects/{name}/project.json.

Centralized layout: every project lives under PROJECT_ROOT_DEFAULT.
Each project's vector store is tagged with name + UTC timestamp at creation,
so re-creates never collide and the audit trail stays clear.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import structlog

from rex.projects.model import PROJECT_ROOT_DEFAULT, Project

logger = structlog.get_logger()


class ProjectStore:
    """Manages projects on disk under PROJECT_ROOT_DEFAULT."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else PROJECT_ROOT_DEFAULT
        self.root.mkdir(parents=True, exist_ok=True)

    # --- CRUD ---

    def create(
        self,
        name: str,
        context: str = "",
        default_source: str | None = None,
        overwrite: bool = False,
    ) -> Project:
        """Create a new project. Raises FileExistsError if exists and overwrite=False."""
        proj_dir = self.root / name
        if proj_dir.exists() and not overwrite:
            existing = self.load(name)
            if existing is not None:
                raise FileExistsError(
                    f"Project '{name}' already exists at {proj_dir}. "
                    f"Use --overwrite to replace."
                )

        if proj_dir.exists() and overwrite:
            logger.warning("project_overwriting", name=name, path=str(proj_dir))
            shutil.rmtree(proj_dir, ignore_errors=True)

        project = Project.new(
            name=name,
            context=context,
            root=self.root / name,
            default_source=default_source,
        )
        project.ensure_dirs()
        self._save(project)
        logger.info("project_created", name=name, vector=project.vector_path)
        return project

    def load(self, name: str) -> Optional[Project]:
        """Load a project by name. Returns None if not found."""
        meta = self.root / name / "project.json"
        if not meta.exists():
            return None
        try:
            data = json.loads(meta.read_text())
            return Project(**data)
        except Exception as e:
            logger.error("project_load_failed", name=name, error=str(e))
            return None

    def list_all(self) -> list[Project]:
        """List all projects sorted by created_at desc."""
        projects = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            p = self.load(d.name)
            if p is not None:
                projects.append(p)
        projects.sort(key=lambda x: x.created_at, reverse=True)
        return projects

    def exists(self, name: str) -> bool:
        """Check if a project exists."""
        return (self.root / name / "project.json").exists()

    def update(self, project: Project) -> None:
        """Persist updates to an existing project."""
        if not self.exists(project.name):
            raise FileNotFoundError(f"Project '{project.name}' does not exist")
        self._save(project)

    def delete(self, name: str, *, also_remove_data: bool = False) -> bool:
        """Delete a project. If also_remove_data, removes vectors/jobs/output.

        Returns True if deleted.
        """
        proj_dir = self.root / name
        if not proj_dir.exists():
            return False
        if also_remove_data:
            shutil.rmtree(proj_dir, ignore_errors=True)
            logger.warning("project_deleted_with_data", name=name)
        else:
            # Just remove project.json — keep data behind for forensics
            meta = proj_dir / "project.json"
            if meta.exists():
                meta.unlink()
            logger.warning("project_metadata_removed", name=name)
        return True

    # --- Helpers ---

    def _save(self, project: Project) -> None:
        """Write project.json."""
        Path(project.root_path).expanduser().mkdir(parents=True, exist_ok=True)
        project.meta_path().write_text(project.model_dump_json(indent=2))
