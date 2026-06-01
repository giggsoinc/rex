"""Rex pipeline — orchestrates Scanner → Router → Organizer sequentially.

Designed for raw asyncio (no Prefect dep for ideation). Easy to swap to Prefect
or any orchestrator later — agents are pluggable via contracts.py protocols.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog

from rex.config import Settings, get_settings
from rex.models.schemas import JobStatus, ScanJob
from rex.orchestrator.contracts import OrganizerAgent, RouterAgent, ScannerAgent
from rex.orchestrator.state import JobStore
from rex.vectorstore import VectorStore

logger = structlog.get_logger()

ProgressCallback = Callable[["PipelineProgress"], Awaitable[None]]


@dataclass
class PipelineProgress:
    """Snapshot of pipeline state for UI/CLI consumption."""

    job_id: str
    status: JobStatus
    total: int = 0
    scanned: int = 0
    routed: int = 0
    organized: int = 0
    duplicates: int = 0
    categories: list[str] = field(default_factory=list)
    current_file: str = ""
    error: str = ""


class RexPipeline:
    """Orchestrates the Scanner → Router → Organizer pipeline.

    Pluggable agents via protocols. Idempotent. Progress-aware.
    """

    def __init__(
        self,
        scanner: ScannerAgent,
        router: RouterAgent,
        organizer: OrganizerAgent,
        vector_store: VectorStore,
        job_store: JobStore,
        settings: Settings | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.scanner = scanner
        self.router = router
        self.organizer = organizer
        self.vector_store = vector_store
        self.job_store = job_store
        self.settings = settings or get_settings()
        self.on_progress = on_progress
        # Stamped by builder when the pipeline belongs to a project
        self.project_name: str = ""
        self.project_output_path: str = ""

    async def run(self, source_path: str, output_path: str | None = None, name: str = "") -> ScanJob:
        """Execute the full pipeline on a source folder.

        Args:
            source_path: Folder to scan.
            output_path: Where to put organized output (defaults to settings).
            name: Optional job name.

        Returns:
            Final job state.
        """
        output_path = output_path or self.settings.storage_path

        # Initialize state + vector store
        await self.vector_store.initialize()
        job = await self.job_store.create_or_resume_job(source_path, output_path, name)
        logger.info("pipeline_start", job_id=job.id, source=source_path, output=output_path)

        progress = PipelineProgress(job_id=job.id, status=JobStatus.SCANNING)

        try:
            # Estimate work
            progress.total = await self.scanner.estimate_count(source_path)
            await self._emit(progress)
            job.total_files = progress.total
            job.status = JobStatus.SCANNING
            await self.job_store.update_job(job)

            # Stage 1: Scan + embed (streams FileContexts)
            contexts = []
            async for ctx in self.scanner.scan(source_path, job.id):
                contexts.append(ctx)
                progress.scanned += 1
                progress.current_file = ctx.file_record.filename
                await self._emit(progress)

            job.scanned_files = progress.scanned
            job.status = JobStatus.ROUTING
            await self.job_store.update_job(job)

            # Stage 2: Route (LLM classify + dedup)
            decisions = {}
            categories_seen: set[str] = set()
            for ctx in contexts:
                # Idempotency: skip if decision already exists
                existing = await self.job_store.get_decision(job.id, ctx.file_record.id)
                if existing is not None:
                    decisions[ctx.file_record.id] = existing
                    progress.routed += 1
                    categories_seen.add(existing.category)
                    if existing.duplicate_of:
                        progress.duplicates += 1
                    continue

                try:
                    decision = await self.router.route(ctx)
                except Exception as e:
                    logger.error("router_failed_for_file", file=ctx.file_record.filename, error=str(e))
                    progress.error = f"Router failed on {ctx.file_record.filename}: {e}"
                    continue

                await self.job_store.save_decision(ctx.file_record.id, job.id, decision)
                decisions[ctx.file_record.id] = decision
                progress.routed += 1
                progress.current_file = ctx.file_record.filename
                categories_seen.add(decision.category)
                if decision.duplicate_of:
                    progress.duplicates += 1
                await self._emit(progress)

                # Small breath between calls to keep Ollama happy
                await asyncio.sleep(0.05)

            job.classified_files = progress.routed
            job.duplicate_count = progress.duplicates
            job.categories_discovered = sorted(categories_seen)
            job.status = JobStatus.ORGANIZING
            await self.job_store.update_job(job)
            progress.categories = job.categories_discovered

            # Stage 3: Organize (move/copy + sidecars)
            for ctx in contexts:
                decision = decisions.get(ctx.file_record.id)
                if decision is None:
                    continue
                try:
                    new_path = await self.organizer.organize(
                        ctx.file_record, decision, output_path
                    )
                    progress.organized += 1
                    progress.current_file = ctx.file_record.filename
                except Exception as e:
                    logger.error("organize_failed", file=ctx.file_record.filename, error=str(e))
                    progress.error = f"Organize failed on {ctx.file_record.filename}: {e}"
                    continue
                await self._emit(progress)

            # Finalize: build catalog
            await self.organizer.finalize(job.id, output_path)

            job.organized_files = progress.organized
            job.status = JobStatus.COMPLETE
            await self.job_store.update_job(job)

            progress.status = JobStatus.COMPLETE
            await self._emit(progress)
            logger.info("pipeline_complete", job_id=job.id, files=progress.organized)
            return job

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            await self.job_store.update_job(job)
            progress.status = JobStatus.FAILED
            progress.error = str(e)
            await self._emit(progress)
            logger.error("pipeline_failed", job_id=job.id, error=str(e))
            raise

    async def _emit(self, progress: PipelineProgress) -> None:
        """Push progress to optional callback."""
        if self.on_progress is not None:
            try:
                await self.on_progress(progress)
            except Exception as e:
                logger.warning("progress_callback_failed", error=str(e))
