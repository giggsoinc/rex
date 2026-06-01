"""Job state store — tracks pipeline progress, supports idempotency.

For ideation: SQLite-backed via aiosqlite. Same interface for enterprise PG.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from rex.models.schemas import FileDecision, FileRecord, JobStatus, ScanJob

logger = structlog.get_logger()


class JobStore:
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
        """Persist job state."""
        meta_file = self._job_dir(job.id) / "job.json"
        meta_file.write_text(job.model_dump_json(indent=2))

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

    # --- File records ---

    async def save_file(self, file_record: FileRecord) -> None:
        """Save a file record to job's files/ directory."""
        path = self._job_dir(file_record.job_id) / "files" / f"{file_record.id}.json"
        path.write_text(file_record.model_dump_json(indent=2, exclude_none=True))

    async def get_file(self, job_id: str, file_id: str) -> FileRecord | None:
        """Load a file record."""
        path = self._job_dir(job_id) / "files" / f"{file_id}.json"
        if not path.exists():
            return None
        return FileRecord(**json.loads(path.read_text()))

    async def get_file_by_hash(self, job_id: str, sha256: str) -> FileRecord | None:
        """Look up file by hash — used for idempotency (skip already-scanned files)."""
        files_dir = self._job_dir(job_id) / "files"
        for f in files_dir.iterdir():
            data = json.loads(f.read_text())
            if data.get("sha256_hash") == sha256:
                return FileRecord(**data)
        return None

    async def list_files(self, job_id: str) -> list[FileRecord]:
        """List all file records for a job."""
        records = []
        for f in (self._job_dir(job_id) / "files").iterdir():
            try:
                records.append(FileRecord(**json.loads(f.read_text())))
            except Exception as e:
                logger.warning("file_record_load_failed", path=str(f), error=str(e))
        return records

    # --- Decisions ---

    async def save_decision(self, file_id: str, job_id: str, decision: FileDecision) -> None:
        """Persist a router decision."""
        path = self._job_dir(job_id) / "decisions" / f"{file_id}.json"
        path.write_text(decision.model_dump_json(indent=2, exclude_none=True))

    async def get_decision(self, job_id: str, file_id: str) -> FileDecision | None:
        """Load a decision."""
        path = self._job_dir(job_id) / "decisions" / f"{file_id}.json"
        if not path.exists():
            return None
        return FileDecision(**json.loads(path.read_text()))

    async def list_decisions(self, job_id: str) -> dict[str, FileDecision]:
        """All decisions for a job, keyed by file_id."""
        out: dict[str, FileDecision] = {}
        for f in (self._job_dir(job_id) / "decisions").iterdir():
            file_id = f.stem
            try:
                out[file_id] = FileDecision(**json.loads(f.read_text()))
            except Exception as e:
                logger.warning("decision_load_failed", path=str(f), error=str(e))
        return out

    # --- Cleanup ---

    async def delete_job(self, job_id: str) -> None:
        """Wipe a job's state."""
        import shutil
        job_dir = self._job_dir(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
