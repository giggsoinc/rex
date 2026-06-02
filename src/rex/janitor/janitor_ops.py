"""Janitor core operations — implemented as a mixin.

`Janitor` inherits `_JanitorOps`, so every `self._merge_shards(...)` etc.
call in janitor.py resolves here unchanged.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

import structlog

from rex.orchestrator.state import JobStore
from rex.projects.model import Project
from rex.vectorstore.lancedb_store import LanceDBStore

logger = structlog.get_logger()


class _JanitorOps:
    """Core cleanup operations mixed into Janitor."""

    async def _merge_shards(self, project: Project) -> int:
        """Merge all per-worker LanceDB shards into the project's canonical vector store."""
        shards_dir = Path(project.vector_path).parent / ".shards"
        if not shards_dir.exists():
            return 0

        main_store = LanceDBStore(db_path=project.vector_path, dim=self.settings.embed_dim)
        await main_store.initialize()

        total = 0
        for shard in shards_dir.iterdir():
            if not shard.is_dir() or not shard.name.endswith(".lance"):
                continue
            try:
                rows = await main_store.merge_from(str(shard))
                total += rows
            except Exception as e:
                logger.warning("janitor_shard_merge_failed", shard=shard.name, error=str(e))

        # Remove shards after successful merge
        try:
            shutil.rmtree(shards_dir)
        except Exception as e:
            logger.warning("janitor_shard_cleanup_failed", error=str(e))

        await main_store.close()
        logger.info("janitor_shards_merged", project=project.name, rows=total)
        return total

    async def _compact_vectors(self, project: Project) -> bool:
        """Compact LanceDB tables — drops fragmentation from upserts."""
        try:
            import lancedb
            db = await asyncio.to_thread(lancedb.connect, project.vector_path)
            tbl = await asyncio.to_thread(db.open_table, "rex_vectors")
            # LanceDB compact API varies — best-effort
            for method in ("compact_files", "optimize"):
                if hasattr(tbl, method):
                    try:
                        await asyncio.to_thread(getattr(tbl, method))
                        return True
                    except Exception:
                        continue
            return True
        except Exception as e:
            logger.warning("janitor_compact_failed", error=str(e))
            return False

    async def _finalize_catalog(self, project: Project, plan_id: str) -> bool:
        """Re-run catalog generation with merged data."""
        try:
            from rex.agents.organizer import LocalOrganizer
            organizer = LocalOrganizer(JobStore(base_path=project.jobs_path), self.settings)
            # The plan-level job id matches what worker uses
            js = JobStore(base_path=project.jobs_path)
            jobs = await js.list_jobs()
            target = next((j for j in jobs if plan_id in (j.name or "")), None)
            if target is None and jobs:
                target = jobs[0]
            if target:
                await organizer.finalize(target.id, project.output_path)
                return True
            return False
        except Exception as e:
            logger.warning("janitor_finalize_failed", error=str(e))
            return False

    async def _cleanup_temp(self, project: Project) -> int:
        """Remove temp dirs (extraction caches, shard remnants)."""
        cleaned = 0
        for candidate in [
            Path(project.root_path) / ".tmp",
            Path(project.vector_path).parent / ".tmp",
            Path(project.vector_path).parent / ".shards",
        ]:
            if candidate.exists():
                try:
                    shutil.rmtree(candidate, ignore_errors=True)
                    cleaned += 1
                except Exception as e:
                    logger.warning("janitor_temp_cleanup_failed", path=str(candidate), error=str(e))
        return cleaned

    async def _mark_job_paused(self, project: Project, plan_id: str) -> None:
        """Set job status to paused."""
        try:
            from rex.models.schemas import JobStatus
            js = JobStore(base_path=project.jobs_path)
            jobs = await js.list_jobs()
            for j in jobs:
                if plan_id in (j.name or "") or plan_id == j.id:
                    j.status = JobStatus.PAUSED
                    await js.update_job(j)
        except Exception as e:
            logger.warning("janitor_mark_paused_failed", error=str(e))

    async def _mark_job_failed(self, project: Project, plan_id: str, error: str) -> None:
        """Set job status to failed with error message."""
        try:
            from rex.models.schemas import JobStatus
            js = JobStore(base_path=project.jobs_path)
            jobs = await js.list_jobs()
            for j in jobs:
                if plan_id in (j.name or "") or plan_id == j.id:
                    j.status = JobStatus.FAILED
                    j.error = error[:500]
                    await js.update_job(j)
        except Exception as e:
            logger.warning("janitor_mark_failed_failed", error=str(e))

    async def _archive_job(self, project: Project, job_id: str) -> None:
        """Move an old job folder to .archive/."""
        try:
            jobs_root = Path(project.jobs_path).expanduser()
            archive_root = jobs_root.parent / ".archive"
            archive_root.mkdir(parents=True, exist_ok=True)
            src = jobs_root / job_id
            if src.exists():
                shutil.move(str(src), str(archive_root / f"{job_id}_{datetime.utcnow().strftime('%Y%m%d')}"))
        except Exception as e:
            logger.warning("janitor_archive_failed", job=job_id, error=str(e))
