"""Job state store — tracks pipeline progress, supports idempotency.

For ideation: SQLite-backed via aiosqlite. Same interface for enterprise PG.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import structlog

from rex.models.schemas import JobStatus, ScanJob
from rex.orchestrator.state_records import RecordsMixin

logger = structlog.get_logger()


class JobStore(RecordsMixin):
    """Lightweight job/file/decision store using JSON files on disk.

    Used for ideation. Enterprise mode swaps to PostgreSQL via the same interface.
    """

    def __init__(self, base_path: str = "~/rex-data/jobs") -> None:
        self.base_path = Path(base_path).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    # --- Idempotent job ID ---

    @staticmethod
    def compute_job_id(source_path: str) -> str:
        """Deterministic job id from source path — same folder = same job_id."""
        digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
        return f"job_{digest}"

    # --- Job CRUD ---

    def _job_dir(self, job_id: str) -> Path:
        d = self.base_path / job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "files").mkdir(exist_ok=True)
        (d / "decisions").mkdir(exist_ok=True)
        return d

    async def create_or_resume_job(self, source_path: str, output_path: str, name: str = "") -> ScanJob:
        """Create job if missing, else resume existing.

        Idempotency: scanning the same folder twice reuses the same job_id.
        """
        job_id = self.compute_job_id(source_path)
        job_dir = self._job_dir(job_id)
        meta_file = job_dir / "job.json"

        if meta_file.exists():
            data = json.loads(meta_file.read_text())
            data.setdefault("name", name or Path(source_path).name)
            return ScanJob(**data)

        job = ScanJob(
            id=job_id,
            name=name or Path(source_path).name,
            source_path=source_path,
            output_path=output_path,
            status=JobStatus.PENDING,
        )
        meta_file.write_text(job.model_dump_json(indent=2))
        return job

    async def update_job(self, job: ScanJob) -> None:
        """Persist job state. Touches last_progress_at unless already terminal."""
        from datetime import datetime
        from rex.models.schemas import JobStatus
        if job.status not in (JobStatus.COMPLETE, JobStatus.FAILED):
            job.last_progress_at = datetime.utcnow()
        meta_file = self._job_dir(job.id) / "job.json"
        meta_file.write_text(job.model_dump_json(indent=2))

    async def touch_progress(
        self, job_id: str, current_file: str | None = None,
        scanned: int | None = None, classified: int | None = None,
        organized: int | None = None,
    ) -> None:
        """Lightweight heartbeat — load job, bump counters + last_progress_at."""
        job = await self.get_job(job_id)
        if job is None:
            return
        if current_file is not None:
            job.current_file = current_file
        if scanned is not None:
            job.scanned_files = scanned
        if classified is not None:
            job.classified_files = classified
        if organized is not None:
            job.organized_files = organized
        await self.update_job(job)

    async def get_job(self, job_id: str) -> ScanJob | None:
        """Load a job by ID."""
        meta_file = self._job_dir(job_id) / "job.json"
        if not meta_file.exists():
            return None
        return ScanJob(**json.loads(meta_file.read_text()))

    async def list_jobs(self) -> list[ScanJob]:
        """List all jobs."""
        jobs = []
        for job_dir in self.base_path.iterdir():
            if not job_dir.is_dir():
                continue
            meta_file = job_dir / "job.json"
            if meta_file.exists():
                jobs.append(ScanJob(**json.loads(meta_file.read_text())))
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    # --- Cleanup ---

    async def delete_job(self, job_id: str) -> None:
        """Wipe a job's state."""
        import shutil
        job_dir = self._job_dir(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
