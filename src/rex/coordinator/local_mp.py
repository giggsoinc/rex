"""Local multiprocessing coordinator — true OS-level parallelism via multiprocessing.

Higher RAM, but bypasses Python GIL. Each worker is its own process with its own
Ollama connections and event loop. Best when you have plenty of RAM and CPUs.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import structlog

from rex.coordinator.base import Coordinator, CoordinatorResult
from rex.planner.model import Batch, BatchStatus, ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project

logger = structlog.get_logger()


def _worker_entry(
    batch_json: str,
    plan_json: str,
    project_json: str,
    intent_json: str,
) -> tuple[str, str, str]:
    """Process-pool entry point. Receives JSON, runs worker, returns JSON result.

    Returns: (batch_id, status, error_string)
    """
    import json
    from rex.agents.worker import RexWorker
    from rex.planner.model import Batch, ScanPlan
    from rex.preflight.intent import ScanIntent
    from rex.projects.model import Project

    batch = Batch(**json.loads(batch_json))
    plan = ScanPlan(**json.loads(plan_json))
    project = Project(**json.loads(project_json))
    intent = ScanIntent(**json.loads(intent_json))

    async def run():
        worker = RexWorker(project=project, intent=intent)
        await worker.initialize()
        await worker.process_batch(batch, plan)

    try:
        asyncio.run(run())
        return (batch.id, "complete", "")
    except Exception as e:
        return (batch.id, "failed", str(e)[:300])


class LocalMultiprocessCoordinator(Coordinator):
    """N batches run in N child Python processes."""

    def name(self) -> str:
        return "local-multiprocess"

    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
    ) -> CoordinatorResult:
        # Serialize once
        plan_json = plan.model_dump_json()
        project_json = project.model_dump_json()
        intent_json = intent.model_dump_json()

        loop = asyncio.get_event_loop()

        def _submit_all() -> dict:
            results: dict[str, tuple[str, str]] = {}
            ctx = mp.get_context("spawn")  # safer than fork on macOS
            with ProcessPoolExecutor(
                max_workers=max_concurrency,
                mp_context=ctx,
            ) as pool:
                futures = {
                    pool.submit(
                        _worker_entry,
                        b.model_dump_json(), plan_json, project_json, intent_json,
                    ): b
                    for b in plan.batches
                }
                for fut in as_completed(futures):
                    try:
                        batch_id, status, err = fut.result()
                        results[batch_id] = (status, err)
                    except Exception as e:
                        batch = futures[fut]
                        results[batch.id] = ("failed", str(e)[:300])
            return results

        results = await loop.run_in_executor(None, _submit_all)

        completed = sum(1 for s, _ in results.values() if s == "complete")
        failed = sum(1 for s, _ in results.values() if s == "failed")
        files = sum(b.count for b in plan.batches if results.get(b.id, ("?", ""))[0] == "complete")

        # Update batch statuses on the plan
        for b in plan.batches:
            status, err = results.get(b.id, ("failed", "no result"))
            b.status = BatchStatus.COMPLETE if status == "complete" else BatchStatus.FAILED
            b.error = err or None
            b.completed_at = datetime.utcnow()

        return CoordinatorResult(
            plan_id=plan.id,
            total_batches=len(plan.batches),
            completed=completed,
            failed=failed,
            skipped=0,
            files_processed=files,
        )
