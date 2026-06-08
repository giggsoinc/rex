"""`rex tail` — stream live job progress like `tail -f`.

Usage:
  rex tail                  # tail the most recent in-progress job
  rex tail --latest         # same as above
  rex tail <job_id>         # tail a specific job by ID

Polls job.json every second; prints a single status line when anything
changes (status, counters, current_file, heartbeat). Exits on Ctrl-C or
when status reaches COMPLETE / FAILED.

Stuck detection: if heartbeat hasn't moved for >5 minutes, prints
"⚠️  STUCK" warning every poll.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone

from rich.console import Console

from rex.models.schemas import JobStatus
from rex.orchestrator.state import JobStore

console = Console()

_STUCK_AFTER = timedelta(minutes=5)


async def _pick_job(store: JobStore, requested: str | None) -> str | None:
    """Pick a job ID to tail. If requested, validate; else use most recent active."""
    jobs = await store.list_jobs()
    if not jobs:
        console.print("[yellow]No jobs found.[/yellow]")
        return None
    if requested and requested != "--latest":
        for j in jobs:
            if j.id == requested or j.id.startswith(requested):
                return j.id
        console.print(f"[red]No job matching '{requested}'.[/red]")
        return None
    # Pick most-recent non-terminal job, or just most recent overall
    for j in jobs:
        if j.status not in (JobStatus.COMPLETE, JobStatus.FAILED):
            return j.id
    return jobs[0].id


def _status_line(job, prev_signature: str) -> tuple[str, str]:
    """Return (signature, line) — line printed when signature changes."""
    sig = (
        f"{job.status.value}|{job.scanned_files}|{job.classified_files}|"
        f"{job.organized_files}|{job.current_file}|{job.last_progress_at}"
    )
    if sig == prev_signature:
        return sig, ""

    hb = job.last_progress_at
    if hb and hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - hb) if hb else None
    stuck = age is not None and age > _STUCK_AFTER
    icon = "⚠️ " if stuck else "🟢"
    age_str = f" idle {int(age.total_seconds())}s" if age else ""

    line = (
        f"{icon} {job.status.value:<18} "
        f"S={job.scanned_files:>4} "
        f"C={job.classified_files:>4} "
        f"O={job.organized_files:>4} "
        f"D={job.duplicate_count:>3}"
        f"{age_str:<14} "
        f"· {job.current_file or '—'}"
    )
    return sig, line


async def tail_loop(job_id: str, store: JobStore) -> None:
    """Main poll loop — prints one line per change, exits on terminal status."""
    prev = ""
    while True:
        job = await store.get_job(job_id)
        if job is None:
            console.print(f"[red]Job {job_id} disappeared.[/red]")
            return
        prev, line = _status_line(job, prev)
        if line:
            console.print(line)
        if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.AWAITING_REVIEW):
            console.print(
                f"\n[green]Done — final status: {job.status.value}[/green]"
            )
            return
        time.sleep(1)


def main(argv: list[str]) -> int:
    """Entry point for `rex tail [job_id|--latest]`."""
    if argv and argv[0] in {"-h", "--help"}:
        console.print(__doc__)
        return 0

    requested = argv[0] if argv else None
    store = JobStore(base_path="~/rex-data/jobs")

    job_id = asyncio.run(_pick_job(store, requested))
    if job_id is None:
        return 1

    console.print(f"[cyan]Tailing job: {job_id}[/cyan] (Ctrl-C to exit)\n")
    try:
        asyncio.run(tail_loop(job_id, store))
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
