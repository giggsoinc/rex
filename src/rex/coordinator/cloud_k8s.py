"""Kubernetes Jobs coordinator — stub for roadmap.

Each batch becomes a K8s Job. Best for enterprise customers with existing K8s.
"""

from __future__ import annotations

from rex.coordinator.base import Coordinator, CoordinatorResult
from rex.planner.model import ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project


class K8sCoordinator(Coordinator):
    """K8s Jobs coordinator. Stub for roadmap."""

    def name(self) -> str:
        return "cloud-k8s"

    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
        cancel_event=None,
    ) -> CoordinatorResult:
        raise NotImplementedError(
            "K8sCoordinator is on the roadmap. Use mode='asyncio' or 'mp' locally for now."
        )
