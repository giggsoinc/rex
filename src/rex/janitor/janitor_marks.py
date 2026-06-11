"""Job-record status markers — mixin for the Janitor.

Split from janitor_ops.py for the 150-line guard. These keep job.json
truthful at run boundaries: paused on kill, failed on crash, complete on
success. The UI renders whatever these write.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from rex.orchestrator.state import JobStore
from rex.projects.model import Project

logger = structlog.get_logger()


class _JanitorMarks:
    """Status-marking helpers mixed into Janitor via _JanitorOps."""

    async def _mark_job(self, project: Project, plan_id: str, **updates) -> None:
        """Apply field updates to every job matching this plan."""
        try:
            js = JobStore(base_path=project.jobs_path)
            for j in await js.list_jobs():
                if plan_id in (j.name or "") or plan_id == j.id:
                    for field, value in updates.items():
                        setattr(j, field, value)
                    await js.update_job(j)
        except Exception as e:
            logger.warning("janitor_mark_failed", updates=list(updates), error=str(e))

    async def _mark_job_paused(self, project: Project, plan_id: str) -> None:
        """Set job status to paused (kill mid-flight)."""
        from rex.models.schemas import JobStatus
        await self._mark_job(project, plan_id, status=JobStatus.PAUSED)

    async def _mark_job_complete(self, project: Project, plan_id: str) -> None:
        """Set job status to complete with completion timestamp."""
        from rex.models.schemas import JobStatus
        await self._mark_job(
            project, plan_id,
            status=JobStatus.COMPLETE, completed_at=datetime.utcnow(),
        )

    async def _mark_job_failed(self, project: Project, plan_id: str, error: str) -> None:
        """Set job status to failed with error message."""
        from rex.models.schemas import JobStatus
        await self._mark_job(
            project, plan_id, status=JobStatus.FAILED, error=error[:500],
        )
