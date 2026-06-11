"""Prefect Cloud coordinator — stub for roadmap.

Each ScanPlan becomes a Prefect flow; each batch becomes a Prefect task.
Best DX, managed retries + observability dashboard.
"""

from __future__ import annotations

from rex.coordinator.base import Coordinator, CoordinatorResult
from rex.planner.model import ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project


class PrefectCoordinator(Coordinator):
    """Prefect-based coordinator. Stub for roadmap."""

    def name(self) -> str:
        return "cloud-prefect"

    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
        cancel_event=None,
    ) -> CoordinatorResult:
        raise NotImplementedError(
            "PrefectCoordinator is on the roadmap. Use mode='asyncio' or 'mp' locally for now."
        )
