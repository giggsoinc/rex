"""Stage-3 dispatch helper — picks SortEngine vs legacy LocalOrganizer.

Extracted from pipeline.py to honor the 150-line file budget. The decision
rule is simple: if a BusinessContext is set on the pipeline (loaded by
builder from .raven/business_context.json), route Stage 3 through the new
SortEngine (Domain/Type taxonomy + _Review/_Unsorted/_Stale buckets +
INDEX.md). Otherwise fall back to LocalOrganizer (type-only folders +
sidecars) for backward compatibility.

Returns the final JobStatus to set on the job (AWAITING_REVIEW for
SortEngine path; COMPLETE for legacy path).
"""

from __future__ import annotations

from typing import Any

import structlog

from rex.models.business_context import BusinessContext
from rex.models.schemas import JobStatus
from rex.orchestrator.contracts import OrganizerAgent
from rex.orchestrator.pipeline_progress import PipelineProgress, ProgressCallback
from rex.orchestrator.pipeline_sort import run_sort_stage
from rex.orchestrator.pipeline_stages import run_organize_stage
from rex.orchestrator.state import JobStore

logger = structlog.get_logger()

__all__ = ["dispatch_stage3"]


async def dispatch_stage3(
    *,
    business_context: BusinessContext | None,
    organizer: OrganizerAgent,
    contexts: list[Any],
    decisions: dict[str, Any],
    output_path: str,
    progress: PipelineProgress,
    emit: ProgressCallback,
    job_store: JobStore,
    job_id: str,
) -> JobStatus:
    """Dispatch Stage 3 to SortEngine or LocalOrganizer.

    Returns the JobStatus the caller should set on the job:
      - AWAITING_REVIEW (SortEngine path; user must clear _Review/_Unsorted/)
      - COMPLETE        (legacy path; no HITL gate)
    """
    if business_context is not None:
        logger.info(
            "pipeline_stage_sort",
            job_id=job_id, domains=business_context.domains,
        )
        await run_sort_stage(
            contexts=contexts,
            decisions=decisions,
            output_path=output_path,
            business_context=business_context,
            progress=progress,
            emit=emit,
            job_store=job_store,
            job_id=job_id,
        )
        # SortEngine writes INDEX.md itself; no organizer.finalize() needed.
        return JobStatus.AWAITING_REVIEW

    logger.info("pipeline_stage_organize_legacy", job_id=job_id)
    await run_organize_stage(
        organizer=organizer,
        contexts=contexts,
        decisions=decisions,
        output_path=output_path,
        progress=progress,
        emit=emit,
    )
    await organizer.finalize(job_id, output_path)
    return JobStatus.COMPLETE
