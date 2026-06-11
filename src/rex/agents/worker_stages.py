"""Stage 1/2 batch loops for RexWorker — split from worker.py for the line guard.

Both loops bound every per-file step with asyncio.wait_for so one
pathological file (huge .doc conversion, slow embed) cannot wedge a worker.
Timed-out files are logged, counted as skipped, and the job heartbeat is
touched so `rex tail` stuck-detection stays accurate.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger()

__all__ = ["scan_batch_files", "route_contexts"]


async def scan_batch_files(
    *, scanner: Any, job_store: Any, batch: Any, job_id: str, timeout: float,
    counts: dict[str, int] | None = None,
) -> tuple[list[Any], int]:
    """Stage 1: scan + embed each file. Returns (contexts, skipped_count)."""
    contexts: list[Any] = []
    skipped = 0
    counts = counts if counts is not None else {"scanned": 0, "classified": 0}
    for bf in batch.files:
        try:
            ctx = await asyncio.wait_for(
                scanner._process_one(bf.path, job_id), timeout=timeout
            )
            if ctx is not None:
                contexts.append(ctx)
            counts["scanned"] += 1
            await job_store.touch_progress(
                job_id, current_file=bf.path, scanned=counts["scanned"]
            )
        except asyncio.TimeoutError:
            skipped += 1
            logger.warning("worker_scan_timeout", file=bf.path, timeout_s=timeout)
            await job_store.touch_progress(job_id, current_file=bf.path)
        except Exception as e:
            logger.warning("worker_scan_skip", file=bf.path, error=str(e)[:120])
    return contexts, skipped


async def route_contexts(
    *, router: Any, job_store: Any, contexts: list[Any], job_id: str, timeout: float,
    counts: dict[str, int] | None = None,
) -> tuple[dict[str, Any], int]:
    """Stage 2: LLM classify + dedup. Returns (decisions, skipped_count)."""
    decisions: dict[str, Any] = {}
    skipped = 0
    counts = counts if counts is not None else {"scanned": 0, "classified": 0}
    for ctx in contexts:
        # Idempotency
        existing = await job_store.get_decision(job_id, ctx.file_record.id)
        if existing is not None:
            decisions[ctx.file_record.id] = existing
            continue
        try:
            decision = await asyncio.wait_for(router.route(ctx), timeout=timeout)
            await job_store.save_decision(ctx.file_record.id, job_id, decision)
            decisions[ctx.file_record.id] = decision
            counts["classified"] += 1
            await job_store.touch_progress(
                job_id, current_file=ctx.file_record.filename,
                classified=counts["classified"],
            )
        except asyncio.TimeoutError:
            skipped += 1
            logger.warning(
                "worker_route_timeout", file=ctx.file_record.filename, timeout_s=timeout
            )
            await job_store.touch_progress(
                job_id, current_file=ctx.file_record.filename
            )
        except Exception as e:
            logger.error("worker_route_failed", file=ctx.file_record.filename, error=str(e)[:120])
        await asyncio.sleep(0.02)
    return decisions, skipped
