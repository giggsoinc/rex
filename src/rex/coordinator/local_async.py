"""Local async coordinator — runs all batches in one process via asyncio.Semaphore.

Fastest startup, single-process. Best for laptops with limited RAM.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

import structlog

from rex.agents.worker import RexWorker
from rex.coordinator.base import Coordinator, CoordinatorResult
from rex.planner.model import Batch, BatchStatus, ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project

logger = structlog.get_logger()


class LocalAsyncCoordinator(Coordinator):
    """N concurrent batches in one Python process via asyncio."""

    def name(self) -> str:
        return "local-asyncio"

    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
        cancel_event: threading.Event | None = None,
    ) -> CoordinatorResult:
        sem = asyncio.Semaphore(max_concurrency)
        worker = RexWorker(project=project, intent=intent)
        await worker.initialize()

        async def run_one(batch: Batch) -> Batch:
            async with sem:
                if cancel_event is not None and cancel_event.is_set():
                    return batch  # stays PENDING — resumable on next run
                batch.status = BatchStatus.IN_PROGRESS
                batch.started_at = datetime.utcnow()
                try:
                    await worker.process_batch(batch, plan)
                    batch.status = BatchStatus.COMPLETE
                except Exception as e:
                    batch.status = BatchStatus.FAILED
                    batch.error = str(e)[:300]
                    logger.error("batch_failed", batch=batch.id, error=str(e))
                batch.completed_at = datetime.utcnow()
                return batch

        results = await asyncio.gather(*(run_one(b) for b in plan.batches), return_exceptions=False)

        completed = sum(1 for b in results if b.status == BatchStatus.COMPLETE)
        failed = sum(1 for b in results if b.status == BatchStatus.FAILED)
        skipped = sum(1 for b in results if b.status == BatchStatus.PENDING)
        files = sum(b.count for b in results if b.status == BatchStatus.COMPLETE)

        return CoordinatorResult(
            plan_id=plan.id,
            total_batches=len(plan.batches),
            completed=completed,
            failed=failed,
            skipped=skipped,
            files_processed=files,
        )
