"""Planner — walks once, segments smart, never calls an LLM.

Speed: 10K files / 5 seconds. Pure os.stat + ext-based grouping.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from pathlib import Path

import structlog

from rex.planner.classify import (
    EXT_TO_TYPE,
    TYPE_SECONDS_PER_FILE,
    build_batches,
    classify_file,
)
from rex.planner.model import (
    Batch,
    BatchType,
    ScanPlan,
    SkippedFile,
)
from rex.utils.skip_rules import SkipRules, is_skip_dir, should_skip, SkipReason

logger = structlog.get_logger()

__all__ = ["Planner", "EXT_TO_TYPE", "TYPE_SECONDS_PER_FILE", "classify_file"]


class Planner:
    """Walks a folder, segments into balanced batches by type/size."""

    def __init__(
        self,
        rules: SkipRules | None = None,
        target_batch_count: int = 4,
        max_files_per_batch: int = 200,
    ) -> None:
        self.rules = rules or SkipRules.default()
        self.target_batch_count = target_batch_count
        self.max_files_per_batch = max_files_per_batch

    async def plan(self, source_path: str, project_name: str) -> ScanPlan:
        """Build a ScanPlan for the source folder.

        Args:
            source_path: Folder to walk.
            project_name: Owning project (for plan provenance).

        Returns:
            ScanPlan with batches + skip list + estimates.
        """
        logger.info("planner_start", source=source_path, project=project_name)

        # 1. Walk + classify (off-thread)
        files, skipped = await asyncio.to_thread(self._walk_classify, source_path)

        # 2. Group by BatchType
        by_type: dict[BatchType, list[tuple[Path, int]]] = defaultdict(list)
        for p, size, t in files:
            by_type[t].append((p, size))

        # 3. Build batches — within each type, split into chunks ≤ max_files_per_batch
        batches: list[Batch] = build_batches(
            by_type, self.target_batch_count, self.max_files_per_batch
        )

        # 4. Files-by-type stats
        files_by_type = {t.value: len(items) for t, items in by_type.items()}

        total_files = sum(len(items) for items in by_type.values())
        total_bytes = sum(s for _, s, _ in files)

        # Time estimate — assume target_batch_count workers in parallel
        max_batch_seconds = max((b.estimated_seconds for b in batches), default=0)
        estimated_seconds = max(60, max_batch_seconds)

        plan = ScanPlan(
            project_name=project_name,
            source_path=str(Path(source_path).resolve()),
            total_files=total_files,
            total_bytes=total_bytes,
            skipped=skipped,
            batches=batches,
            estimated_seconds=estimated_seconds,
            estimated_tokens_in=total_files * 800,
            estimated_tokens_out=total_files * 150,
            files_by_type=files_by_type,
        )
        logger.info(
            "planner_complete",
            files=total_files,
            skipped=len(skipped),
            batches=len(batches),
            est_sec=estimated_seconds,
        )
        return plan

    def _walk_classify(
        self,
        source_path: str,
    ) -> tuple[list[tuple[Path, int, BatchType]], list[SkippedFile]]:
        """Synchronous walk + classify. Off-thread caller."""
        files: list[tuple[Path, int, BatchType]] = []
        skipped: list[SkippedFile] = []
        root = Path(source_path).expanduser().resolve()

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune dirs
            dirnames[:] = [d for d in dirnames if not is_skip_dir(d, self.rules)]
            for filename in filenames:
                fpath = Path(dirpath) / filename
                reason = should_skip(fpath, self.rules)
                if reason != SkipReason.NONE:
                    try:
                        sz = fpath.stat().st_size
                    except OSError:
                        sz = 0
                    skipped.append(SkippedFile(
                        path=str(fpath),
                        reason=reason.value,
                        size_bytes=sz,
                    ))
                    continue
                try:
                    sz = fpath.stat().st_size
                except (PermissionError, OSError):
                    skipped.append(SkippedFile(path=str(fpath), reason="permission_denied", size_bytes=0))
                    continue
                bt = classify_file(fpath, sz)
                files.append((fpath, sz, bt))

        return files, skipped
