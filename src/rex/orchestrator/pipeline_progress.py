"""Pipeline progress snapshot + callback type for UI/CLI consumption."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from rex.models.schemas import JobStatus

ProgressCallback = Callable[["PipelineProgress"], Awaitable[None]]


@dataclass
class PipelineProgress:
    """Snapshot of pipeline state for UI/CLI consumption."""

    job_id: str
    status: JobStatus
    total: int = 0
    scanned: int = 0
    routed: int = 0
    organized: int = 0
    duplicates: int = 0
    categories: list[str] = field(default_factory=list)
    current_file: str = ""
    error: str = ""
