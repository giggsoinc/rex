"""Cross-process job control — PID files + CANCEL sentinel + watcher.

A UI or another CLI process cannot set an in-process threading.Event, so
kill requests travel through the filesystem: touching `<job_dir>/CANCEL`
asks the running scan to drain (in-flight batches finish, queued ones stay
PENDING). The PID file enables force-kill (SIGINT) and crash detection.
"""

from __future__ import annotations

import os
import signal
import threading
from pathlib import Path

import structlog

logger = structlog.get_logger()

__all__ = [
    "job_dir_for", "write_pid", "read_pid", "pid_alive",
    "request_cancel", "cancel_requested", "clear_cancel",
    "force_kill", "CancelFileWatcher",
]


def job_dir_for(jobs_path: str, source_path: str) -> Path:
    """Resolve the job directory for a source folder (same hash as JobStore)."""
    from rex.orchestrator.state import JobStore
    job_id = JobStore.compute_job_id(source_path)
    return Path(jobs_path).expanduser().resolve() / job_id


def write_pid(job_dir: Path, pid: int | None = None) -> None:
    """Record the scan process PID for force-kill / crash detection."""
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "pid").write_text(str(pid or os.getpid()))


def read_pid(job_dir: Path) -> int | None:
    """Return the recorded PID, or None."""
    f = job_dir / "pid"
    try:
        return int(f.read_text().strip()) if f.exists() else None
    except ValueError:
        return None


def pid_alive(pid: int) -> bool:
    """True if a process with this PID exists (signal 0 probe)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def request_cancel(job_dir: Path) -> None:
    """Ask the running scan to drain gracefully."""
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "CANCEL").touch()


def cancel_requested(job_dir: Path) -> bool:
    """True if a cancel sentinel exists."""
    return (job_dir / "CANCEL").exists()


def clear_cancel(job_dir: Path) -> None:
    """Remove a stale sentinel (called at scan start)."""
    (job_dir / "CANCEL").unlink(missing_ok=True)


def force_kill(job_dir: Path) -> bool:
    """SIGINT the recorded scan process. Returns True if signalled."""
    pid = read_pid(job_dir)
    if pid is None or not pid_alive(pid):
        return False
    os.kill(pid, signal.SIGINT)
    logger.warning("job_force_kill", pid=pid, job_dir=str(job_dir))
    return True


class CancelFileWatcher:
    """Background thread: polls for the CANCEL sentinel, sets cancel_event."""

    def __init__(self, job_dir: Path, cancel_event: threading.Event,
                 interval: float = 1.0) -> None:
        """Watch job_dir for CANCEL every `interval` seconds."""
        self.job_dir = job_dir
        self.cancel_event = cancel_event
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin watching (daemon thread — never blocks exit)."""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        """Poll until cancelled, stopped, or sentinel found."""
        while not self._stop.is_set() and not self.cancel_event.is_set():
            if cancel_requested(self.job_dir):
                logger.warning("cancel_sentinel_detected", job_dir=str(self.job_dir))
                self.cancel_event.set()
                return
            self._stop.wait(self.interval)

    def stop(self) -> None:
        """Stop watching."""
        self._stop.set()
