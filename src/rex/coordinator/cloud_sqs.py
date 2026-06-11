"""AWS SQS coordinator — stub for roadmap.

Architecture (when implemented):
  - Each batch becomes one SQS message
  - Workers run as Fargate tasks, polling SQS
  - Heartbeat → DynamoDB or ElastiCache
  - Failed batches go to DLQ
  - Coordinator polls for completion
"""

from __future__ import annotations

from rex.coordinator.base import Coordinator, CoordinatorResult
from rex.planner.model import ScanPlan
from rex.preflight.intent import ScanIntent
from rex.projects.model import Project


class SqsCoordinator(Coordinator):
    """AWS SQS-based coordinator. Stub for roadmap."""

    def name(self) -> str:
        return "cloud-sqs"

    async def run_plan(
        self,
        plan: ScanPlan,
        project: Project,
        intent: ScanIntent,
        max_concurrency: int = 4,
        cancel_event=None,
    ) -> CoordinatorResult:
        raise NotImplementedError(
            "SqsCoordinator is on the roadmap. Use mode='asyncio' or 'mp' locally for now."
        )
