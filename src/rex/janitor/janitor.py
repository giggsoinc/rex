"""Janitor — cleanup crew.

Triggers:
  ON_COMPLETE — after coordinator finishes; merge shards, compact, finalize.
  ON_KILL     — SIGINT/SIGTERM; save checkpoints, mark paused.
  ON_CRASH    — orphan detection (worker shards without complete batches).
  PERIODIC    — daily cron; sweep old paused/failed jobs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

import structlog

from rex.config import get_settings
from rex.janitor.janitor_ops import _JanitorOps
from rex.orchestrator.state import JobStore
from rex.projects.model import Project
from rex.projects.store import ProjectStore

logger = structlog.get_logger()


class JanitorTrigger(str, Enum):
    """Why the Janitor was invoked."""

    ON_COMPLETE = "on_complete"
    ON_KILL = "on_kill"
    ON_CRASH = "on_crash"
    PERIODIC = "periodic"
    MANUAL = "manual"


class Janitor(_JanitorOps):
    """Cleanup coordinator."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    # --- Trigger entry points ---

    async def on_complete(self, project: Project, plan_id: str) -> dict:
        """Called after coordinator completes successfully."""
        logger.info("janitor_on_complete", project=project.name, plan=plan_id)
        merged_rows = await self._merge_shards(project)
        compact = await self._compact_vectors(project)
        finalized = await self._finalize_catalog(project, plan_id)
        cleaned = await self._cleanup_temp(project)
        return {
            "trigger": JanitorTrigger.ON_COMPLETE.value,
            "merged_rows": merged_rows,
            "compacted": compact,
            "catalog_finalized": finalized,
            "temp_cleaned": cleaned,
        }

    async def on_kill(self, project: Project, plan_id: str) -> dict:
        """Called when user kills the run mid-flight."""
        logger.warning("janitor_on_kill", project=project.name, plan=plan_id)
        merged = await self._merge_shards(project)
        await self._mark_job_paused(project, plan_id)
        return {
            "trigger": JanitorTrigger.ON_KILL.value,
            "merged_rows": merged,
            "status": "paused",
        }

    async def on_crash(self, project: Project, plan_id: str, error: str = "") -> dict:
        """Called when a worker or coordinator crashes."""
        logger.error("janitor_on_crash", project=project.name, plan=plan_id, error=error)
        merged = await self._merge_shards(project)
        await self._mark_job_failed(project, plan_id, error)
        return {
            "trigger": JanitorTrigger.ON_CRASH.value,
            "merged_rows": merged,
            "error": error,
        }

    async def periodic_sweep(self, older_than_days: int = 7) -> dict:
        """Daily sweep — find orphaned paused/failed jobs older than threshold."""
        logger.info("janitor_periodic_start", days=older_than_days)
        store = ProjectStore()
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        archived = 0

        for project in store.list_all():
            try:
                jobs = await JobStore(base_path=project.jobs_path).list_jobs()
                for j in jobs:
                    if j.status.value in {"failed", "paused"} and j.created_at < cutoff:
                        # Archive (move to .archive folder, don't delete)
                        await self._archive_job(project, j.id)
                        archived += 1
            except Exception as e:
                logger.warning("janitor_periodic_project_skip", project=project.name, error=str(e))

        return {"trigger": JanitorTrigger.PERIODIC.value, "archived": archived}
