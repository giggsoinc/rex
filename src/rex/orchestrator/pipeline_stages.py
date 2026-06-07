"""Pipeline stage helpers — route + organize loops.

Sort stage lives in pipeline_sort.py (line budget). Re-exported here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from rex.orchestrator.contracts import OrganizerAgent, RouterAgent
from rex.orchestrator.pipeline_progress import PipelineProgress, ProgressCallback
from rex.orchestrator.pipeline_sort import run_sort_stage  # re-export
from rex.orchestrator.state import JobStore

__all__ = ["run_route_stage", "run_organize_stage", "run_sort_stage"]

logger = structlog.get_logger()


async def run_route_stage(
    *,
    router: RouterAgent,
    job_store: JobStore,
    job_id: str,
    contexts: list[Any],
    progress: PipelineProgress,
    categories_seen: set[str],
    emit: ProgressCallback,
) -> dict[str, Any]:
    """Stage 2: LLM classify + dedup. Returns decisions keyed by file_id.

    Persists progress per-file: counter + current_file + heartbeat written to
    job.json so external readers (Jobs page, rex tail, stuck-detector) see the
    live truth, not a lagging snapshot.
    """
    decisions: dict[str, Any] = {}
    for ctx in contexts:
        # Idempotency: skip if decision already exists
        existing = await job_store.get_decision(job_id, ctx.file_record.id)
        if existing is not None:
            decisions[ctx.file_record.id] = existing
            progress.routed += 1
            categories_seen.add(existing.category)
            if existing.duplicate_of:
                progress.duplicates += 1
            continue

        try:
            decision = await router.route(ctx)
        except Exception as e:
            logger.error("router_failed_for_file", file=ctx.file_record.filename, error=str(e))
            progress.error = f"Router failed on {ctx.file_record.filename}: {e}"
            continue

        await job_store.save_decision(ctx.file_record.id, job_id, decision)
        decisions[ctx.file_record.id] = decision
        progress.routed += 1
        progress.current_file = ctx.file_record.filename
        categories_seen.add(decision.category)
        if decision.duplicate_of:
            progress.duplicates += 1
        # Heartbeat: persist per-file so Jobs page / rex tail see live progress
        await job_store.touch_progress(
            job_id, current_file=ctx.file_record.filename,
            classified=progress.routed,
        )
        await emit(progress)

        # Small breath between calls to keep Ollama happy
        await asyncio.sleep(0.05)
    return decisions


async def run_organize_stage(
    *,
    organizer: OrganizerAgent,
    contexts: list[Any],
    decisions: dict[str, Any],
    output_path: str,
    progress: PipelineProgress,
    emit: ProgressCallback,
    job_store: JobStore | None = None,
    job_id: str | None = None,
) -> None:
    """Stage 3 (legacy): move/copy + sidecars for each routed file.

    If job_store + job_id are supplied, persists per-file heartbeat for the
    Jobs page / rex tail.
    """
    for ctx in contexts:
        decision = decisions.get(ctx.file_record.id)
        if decision is None:
            continue
        try:
            new_path = await organizer.organize(
                ctx.file_record, decision, output_path
            )
            progress.organized += 1
            progress.current_file = ctx.file_record.filename
        except Exception as e:
            logger.error("organize_failed", file=ctx.file_record.filename, error=str(e))
            progress.error = f"Organize failed on {ctx.file_record.filename}: {e}"
            continue
        if job_store and job_id:
            await job_store.touch_progress(
                job_id, current_file=ctx.file_record.filename,
                organized=progress.organized,
            )
        await emit(progress)


