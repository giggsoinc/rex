"""Job page actions — ETA from observed pace, kill controls, crash marking.

ETA deliberately ignores the planner estimate after the first samples:
observed pace (heartbeat counter deltas) is the only number that survives
contact with a pathological PDF eating its full per-file timeout.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import streamlit as st

from rex.models.schemas import JobStatus
from rex.orchestrator.job_control import (
    cancel_requested,
    force_kill,
    pid_alive,
    read_pid,
    request_cancel,
)

_CRASH_AFTER = timedelta(minutes=10)  # stale heartbeat + dead pid → crashed


def _progress_units(job) -> int:
    """Monotonic work counter across stages."""
    return job.scanned_files + job.classified_files + job.organized_files


def eta_text(job) -> str:
    """Rolling-pace ETA. Returns '' until enough samples exist."""
    if job.total_files <= 0 or job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
        return ""
    hist = st.session_state.setdefault("_job_pace", {}).setdefault(job.id, [])
    hist.append((time.monotonic(), _progress_units(job)))
    del hist[:-30]  # keep last 30 samples (~1 min at 2s polls)
    if len(hist) < 5 or hist[-1][1] <= hist[0][1]:
        return "ETA: estimating…"
    pace = (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0])  # units/sec
    remaining = max(0, 3 * job.total_files - _progress_units(job))
    secs = int(remaining / pace)
    if secs < 90:
        return f"ETA: ~{secs}s"
    return f"ETA: ~{secs // 60}m {secs % 60}s"


def mark_if_crashed(store, job, job_dir) -> bool:
    """Detached process died (laptop closed, kill -9)? Mark job FAILED."""
    if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.AWAITING_REVIEW):
        return False
    hb = job.last_progress_at
    if hb is None:
        return False
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - hb < _CRASH_AFTER:
        return False
    pid = read_pid(job_dir)
    if pid is not None and pid_alive(pid):
        return False  # alive but slow — stuck detection handles messaging
    job.status = JobStatus.FAILED
    job.error = "Process died without checkpoint (no heartbeat, PID gone)."
    asyncio.run(store.update_job(job))
    return True


def render_kill_controls(job, job_dir) -> None:
    """Kill (graceful drain) + Force kill buttons with draining state."""
    pid = read_pid(job_dir)
    running = pid is not None and pid_alive(pid)
    if not running:
        return
    if cancel_requested(job_dir):
        st.warning("⏳ Draining — in-flight batches are finishing, the rest are skipped.")
        if st.button("☠️ Force kill now", key=f"force_{job.id}"):
            force_kill(job_dir)
            st.toast(f"SIGINT sent to job {job.id} — janitor is checkpointing.", icon="🛑")
            st.rerun()
        return
    if st.button("⏹ Kill job", key=f"kill_{job.id}",
                 help="Graceful: finishes in-flight batches, skips the rest"):
        request_cancel(job_dir)
        st.toast(f"Cancel requested for {job.id} — draining…", icon="🛑")
        st.rerun()
