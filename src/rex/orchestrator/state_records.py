"""File-record and decision persistence — mixin for JobStore.

Split out of state.py to satisfy the 150-line file limit. Relies on the host
class providing `_job_dir(job_id) -> Path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from rex.models.schemas import FileDecision, FileRecord

logger = structlog.get_logger()


class RecordsMixin:
    """File-record and decision CRUD. Host must provide `_job_dir`."""

    def _job_dir(self, job_id: str) -> Path:  # pragma: no cover - provided by host
        raise NotImplementedError

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
