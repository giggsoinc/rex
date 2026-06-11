"""Coordinator abstract interface — all backends implement this."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from rex.planner.model import Batch, ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project


class WorkerMode(str, Enum):
    """How workers are run locally."""

    ASYNCIO = "asyncio"        # single process, N concurrent tasks
    MULTIPROCESS = "mp"        # N separate processes


@dataclass
class CoordinatorResult:
    """Aggregate result after all batches done."""

    plan_id: str
    total_batches: int
    completed: int
    failed: int
    skipped: int
    files_processed: int


class Coordinator(ABC):
    """Abstract coordinator — backends: local (asyncio/mp), cloud (sqs, prefect, k8s)."""

    @abstractmethod
    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
        cancel_event: threading.Event | None = None,
    ) -> CoordinatorResult:
        """Execute a ScanPlan by dispatching batches to workers.

        Returns when all batches complete (or are abandoned). When
        cancel_event is set mid-run, in-flight batches finish but no new
        batches start; unstarted batches stay PENDING and are counted in
        CoordinatorResult.skipped.
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Identifier for logging."""
        ...
