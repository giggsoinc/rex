"""BusinessContext persistence — load/save per-scan context JSON.

Two storage scopes:
  - Per-project context  → .raven/business_context.json (workspace default)
  - Per-job context      → ~/rex-data/contexts/{job_id}.json (scan-specific)

Per-job overrides per-project; defaults apply if neither file exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from rex.models.business_context import BusinessContext, ModelProfile

logger = structlog.get_logger()

__all__ = ["ContextStore"]

_DEFAULT_DIR = Path("~/rex-data/contexts").expanduser()
_PROJECT_PATH = Path(".raven/business_context.json")


class ContextStore:
    """Load/save BusinessContext objects with per-job and per-project scopes."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        """Construct the context store with an optional override base dir."""
        self.base_dir = Path(base_dir).expanduser() if base_dir else _DEFAULT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # --- Per-job ---

    def _job_path(self, job_id: str) -> Path:
        """Resolve the per-job context file path."""
        return self.base_dir / f"{job_id}.json"

    def get_for_job(self, job_id: str) -> BusinessContext | None:
        """Load BusinessContext for a specific job. None if not found."""
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return BusinessContext(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("context_load_failed", job_id=job_id, error=str(e))
            return None

    def save_for_job(self, job_id: str, context: BusinessContext) -> Path:
        """Persist BusinessContext for a job. Returns the file path."""
        path = self._job_path(job_id)
        path.write_text(context.model_dump_json(indent=2))
        logger.info("context_saved_job", job_id=job_id, path=str(path))
        return path

    # --- Per-project (.raven/business_context.json) ---

    def get_for_project(self, project_root: Path | str = ".") -> BusinessContext | None:
        """Load default BusinessContext for the current project."""
        path = Path(project_root) / _PROJECT_PATH
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return BusinessContext(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("project_context_load_failed", path=str(path), error=str(e))
            return None

    def save_for_project(
        self, context: BusinessContext, project_root: Path | str = "."
    ) -> Path:
        """Persist BusinessContext as project-wide default."""
        path = Path(project_root) / _PROJECT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(context.model_dump_json(indent=2))
        logger.info("context_saved_project", path=str(path))
        return path

    # --- Convenience ---

    @staticmethod
    def default() -> BusinessContext:
        """Return a sensible default BusinessContext for first-time users."""
        return BusinessContext(
            business="",
            domains=[],
            confidence_threshold=0.7,
            model_profile=ModelProfile.BALANCED,
            build_knowledge_graph=True,
        )

    def list_job_contexts(self) -> list[str]:
        """List all job IDs that have a saved context."""
        return sorted(
            p.stem for p in self.base_dir.glob("*.json") if p.is_file()
        )
