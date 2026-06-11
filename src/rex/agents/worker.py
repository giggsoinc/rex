"""RexWorker — processes ONE batch through Scanner → Router → Organizer.

A worker is a Rex pipeline scoped to a specific batch's file list.
Writes to a per-worker LanceDB shard so multiple workers don't contend.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from rex.agents.organizer import LocalOrganizer
from rex.agents.router import LLMRouter
from rex.agents.scanner import LocalScanner
from rex.agents.worker_stages import route_contexts, scan_batch_files
from rex.config import Settings, VisionProvider, get_settings
from rex.ml.provider import ModelProvider
from rex.ml.vision import VisionEngine
from rex.models.schemas import JobStatus
from rex.orchestrator.pipeline_dispatch import dispatch_stage3
from rex.orchestrator.pipeline_progress import PipelineProgress
from rex.orchestrator.state import JobStore
from rex.planner.model import Batch, BatchFile, ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.context_store import ContextStore
from rex.projects.model import Project
from rex.vectorstore.lancedb_store import LanceDBStore

logger = structlog.get_logger()


class RexWorker:
    """One worker handles one batch of files at a time.

    Uses a per-worker LanceDB shard. Coordinator merges shards at the end.
    """

    def __init__(
        self,
        project: Project,
        intent: ScanIntent,
        worker_id: Optional[str] = None,
        settings: Settings | None = None,
    ) -> None:
        self.project = project
        self.intent = intent
        self.worker_id = worker_id or f"w_{datetime.utcnow().strftime('%H%M%S%f')}"
        # Per-worker settings override
        s = settings or get_settings()
        s.llm_provider = type(s.llm_provider)(intent.llm_provider) if hasattr(type(s.llm_provider), intent.llm_provider.upper()) else s.llm_provider
        s.llm_model = intent.llm_model
        self.settings = s

        # Sharded vector store
        shard_path = Path(project.vector_path).parent / f".shards" / f"{self.worker_id}.lance"
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        self.shard_path = str(shard_path)

        self.model = ModelProvider(self.settings)
        self.vision = VisionEngine(self.settings)
        self.vector_store = LanceDBStore(db_path=self.shard_path, dim=self.settings.embed_dim)
        self.job_store = JobStore(base_path=project.jobs_path)

        self.scanner = LocalScanner(
            model_provider=self.model,
            vision_engine=self.vision,
            vector_store=self.vector_store,
            job_store=self.job_store,
            settings=self.settings,
        )
        self.router = LLMRouter(self.model, self.settings)
        self.router.project_context = project.context
        self.organizer = LocalOrganizer(self.job_store, self.settings)
        # Shared across concurrent batches (local_async) so counters accumulate
        self.counts: dict[str, int] = {"scanned": 0, "classified": 0}

    async def initialize(self) -> None:
        """One-time setup."""
        await self.vector_store.initialize()
        logger.info("worker_initialized", worker_id=self.worker_id, shard=self.shard_path)

    async def process_batch(self, batch: Batch, plan: ScanPlan) -> None:
        """Process every file in this batch through the full pipeline."""
        # Use plan id as job id — all batches in a plan share one logical job
        job = await self.job_store.create_or_resume_job(
            source_path=plan.source_path,
            output_path=self.project.output_path,
            name=f"{plan.project_name}_{plan.id}",
        )
        # Keep the job record honest — UI reads it (status, totals, heartbeat)
        if job.status == JobStatus.PENDING or job.total_files != plan.total_files:
            job.status = JobStatus.SCANNING
            job.total_files = plan.total_files
            await self.job_store.update_job(job)
        logger.info(
            "worker_batch_start",
            worker=self.worker_id, batch=batch.id, type=batch.type.value,
            files=batch.count,
        )

        # Stages 1+2: scan + route, each per-file step timeout-bounded
        timeout = self.settings.file_timeout_seconds
        contexts, scan_skipped = await scan_batch_files(
            scanner=self.scanner, job_store=self.job_store,
            batch=batch, job_id=job.id, timeout=timeout, counts=self.counts,
        )
        decisions, route_skipped = await route_contexts(
            router=self.router, job_store=self.job_store,
            contexts=contexts, job_id=job.id, timeout=timeout, counts=self.counts,
        )
        skipped = scan_skipped + route_skipped

        # Stage 3: Dispatch (SortEngine if BusinessContext else legacy). Counts.
        progress = PipelineProgress(job_id=job.id, status=JobStatus.ORGANIZING)
        progress.organized = 0
        cs = ContextStore()
        bc = cs.get_for_project(self.project.root_path) or cs.get_for_project()
        bc = bc if (bc and bc.domains) else None
        attempted = sum(1 for c in contexts if decisions.get(c.file_record.id))
        async def _noemit(p): pass
        try:
            status = await dispatch_stage3(
                business_context=bc, organizer=self.organizer, contexts=contexts,
                decisions=decisions, output_path=self.project.output_path,
                progress=progress, emit=_noemit,
                job_store=self.job_store, job_id=job.id,
            )
        except Exception as e:
            logger.error("worker_dispatch_failed", error=str(e)[:200])
            status = JobStatus.FAILED
        logger.info(
            "worker_batch_complete", worker=self.worker_id, batch=batch.id,
            scanned=len(contexts), routed=len(decisions),
            organized=progress.organized, organize_failed=attempted - progress.organized,
            skipped_timeout=skipped + progress.skipped,
            status=getattr(status, 'value', str(status)), sort_engine=bool(bc),
        )

    async def close(self) -> None:
        """Cleanup connections."""
        await self.vector_store.close()
