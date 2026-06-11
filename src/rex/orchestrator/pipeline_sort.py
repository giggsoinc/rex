"""Sort stage — SortEngine-driven placement (two-phase pipeline path).

Split from pipeline_stages.py to honor the 150-line-per-file Raven guard.
Identical contract to the legacy run_organize_stage but uses BusinessContext
and the SortEngine plug-and-play taxonomy / _Review / _Unsorted buckets.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog

from rex.agents.sort_engine import SortEngine
from rex.config import get_settings
from rex.agents.version_detector import detect_versions
from rex.models.business_context import BusinessContext
from rex.orchestrator.pipeline_progress import PipelineProgress, ProgressCallback
from rex.orchestrator.state import JobStore

logger = structlog.get_logger()

__all__ = ["run_sort_stage"]


async def run_sort_stage(
    *,
    contexts: list[Any],
    decisions: dict[str, Any],
    output_path: str,
    business_context: BusinessContext,
    progress: PipelineProgress,
    emit: ProgressCallback,
    job_store: JobStore | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Stage 3 (two-phase): SortEngine placement + root INDEX.md.

    Returns a placements map (file_id → SortDecision) and writes INDEX.md.
    Files needing review remain in _Review/ until HITL clears them.
    Persists per-file heartbeat when job_store + job_id are supplied.
    """
    # Version supersession pass — mark older V<N> files for _Stale/ before placement
    records = [ctx.file_record for ctx in contexts]
    version_map = detect_versions(records)
    if version_map:
        logger.info("version_supersession_active", stale_count=len(version_map))

    engine = SortEngine(version_map=version_map)
    placements: dict[str, Any] = {}
    out_root = Path(output_path).expanduser().resolve()
    timeout = get_settings().file_timeout_seconds

    for ctx in contexts:
        decision = decisions.get(ctx.file_record.id)
        if decision is None:
            continue
        try:
            sort = await asyncio.wait_for(
                engine.place(ctx.file_record, decision, business_context, out_root),
                timeout=timeout,
            )
            placements[ctx.file_record.id] = sort
            progress.organized += 1
            progress.current_file = ctx.file_record.filename
        except asyncio.TimeoutError:
            progress.skipped += 1
            logger.warning(
                "sort_timeout", file=ctx.file_record.filename, timeout_s=timeout
            )
            if job_store and job_id:
                await job_store.touch_progress(
                    job_id, current_file=ctx.file_record.filename
                )
            continue
        except Exception as e:
            logger.error(
                "sort_failed", file=ctx.file_record.filename, error=str(e)
            )
            progress.error = f"Sort failed on {ctx.file_record.filename}: {e}"
            continue
        if job_store and job_id:
            await job_store.touch_progress(
                job_id, current_file=ctx.file_record.filename,
                organized=progress.organized,
            )
        await emit(progress)

    engine.write_index(out_root, business_context)
    return placements
