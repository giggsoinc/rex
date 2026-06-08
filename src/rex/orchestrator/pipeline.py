"""Rex pipeline — orchestrates Scanner → Router → Organize/Sort. Asyncio."""

from __future__ import annotations

import structlog

from rex.config import Settings, get_settings
from rex.models.business_context import BusinessContext
from rex.models.schemas import JobStatus, ScanJob
from rex.orchestrator.contracts import OrganizerAgent, RouterAgent, ScannerAgent
from rex.orchestrator.pipeline_dispatch import dispatch_stage3
from rex.orchestrator.pipeline_progress import PipelineProgress, ProgressCallback
from rex.orchestrator.pipeline_stages import run_route_stage
from rex.orchestrator.state import JobStore
from rex.vectorstore import VectorStore

logger = structlog.get_logger()


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
        # When set, Stage 3 dispatches to SortEngine (Domain/Type + _Review/
        # _Unsorted/_Stale + INDEX.md). Else legacy LocalOrganizer.
        self.business_context: BusinessContext | None = None

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
            categories_seen: set[str] = set()
            decisions = await run_route_stage(
                router=self.router,
                job_store=self.job_store,
                job_id=job.id,
                contexts=contexts,
                progress=progress,
                categories_seen=categories_seen,
                emit=self._emit,
            )

            job.classified_files = progress.routed
            job.duplicate_count = progress.duplicates
            job.categories_discovered = sorted(categories_seen)
            job.status = JobStatus.ORGANIZING
            await self.job_store.update_job(job)
            progress.categories = job.categories_discovered

            # Stage 3: Dispatch — SortEngine when BusinessContext set,
            # else legacy LocalOrganizer. See pipeline_dispatch.py.
            job.status = await dispatch_stage3(
                business_context=self.business_context,
                organizer=self.organizer,
                contexts=contexts,
                decisions=decisions,
                output_path=output_path,
                progress=progress,
                emit=self._emit,
                job_store=self.job_store,
                job_id=job.id,
            )
            job.organized_files = progress.organized
            await self.job_store.update_job(job)

            progress.status = job.status
            await self._emit(progress)
            logger.info(
                "pipeline_complete", job_id=job.id,
                files=progress.organized, status=job.status.value,
            )
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
