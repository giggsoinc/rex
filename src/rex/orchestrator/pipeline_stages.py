"""Pipeline stage helpers — route, organize, and sort loops.

Pure mechanical extraction to satisfy the 150-line file limit. These are free
functions operating on the agents/stores passed in; RexPipeline.run drives them.

Two organize paths:
  - run_organize_stage  — legacy LocalOrganizer (flat category folders + sidecars).
  - run_sort_stage      — two-phase SortEngine (BusinessContext aware, type buckets,
                          _Review/_Unsorted/_Trash buckets, root INDEX.md).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

from rex.agents.sort_engine import SortEngine
from rex.models.schemas import BusinessContext
from rex.orchestrator.contracts import OrganizerAgent, RouterAgent
from rex.orchestrator.pipeline_progress import PipelineProgress, ProgressCallback
from rex.orchestrator.state import JobStore

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
    """Stage 2: LLM classify + dedup. Returns decisions keyed by file_id."""
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
) -> None:
    """Stage 3 (legacy): move/copy + sidecars for each routed file."""
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
        await emit(progress)


async def run_sort_stage(
    *,
    contexts: list[Any],
    decisions: dict[str, Any],
    output_path: str,
    business_context: BusinessContext,
    progress: PipelineProgress,
    emit: ProgressCallback,
) -> dict[str, Any]:
    """Stage 3 (two-phase): SortEngine placement + root INDEX.md.

    Returns a placements map (file_id → SortDecision) and writes INDEX.md.
    Files needing review remain in _Review/ until HITL clears them.
    """
    engine = SortEngine()
    placements: dict[str, Any] = {}
    out_root = Path(output_path).expanduser().resolve()

    for ctx in contexts:
        decision = decisions.get(ctx.file_record.id)
        if decision is None:
            continue
        try:
            sort = await engine.place(
                ctx.file_record, decision, business_context, out_root
            )
            placements[ctx.file_record.id] = sort
            progress.organized += 1
            progress.current_file = ctx.file_record.filename
        except Exception as e:
            logger.error("sort_failed", file=ctx.file_record.filename, error=str(e))
            progress.error = f"Sort failed on {ctx.file_record.filename}: {e}"
            continue
        await emit(progress)

    engine.write_index(out_root, business_context)
    return placements
