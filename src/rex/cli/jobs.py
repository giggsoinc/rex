"""`rex jobs` — list and kill scan jobs across all project job stores.

  rex jobs                      list jobs
  rex jobs kill <job_id>        graceful drain (touch CANCEL sentinel)
  rex jobs kill <job_id> -f     force: SIGINT the recorded scan PID
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console

from rex.cli.tail import _all_stores
from rex.orchestrator.job_control import (
    force_kill,
    pid_alive,
    read_pid,
    request_cancel,
)

console = Console()


def _find_job_dir(job_id: str):
    """Locate a job's directory across global + per-project stores."""
    for store in _all_stores():
        d = store.base_path / job_id
        if (d / "job.json").exists():
            return d
    return None


def _list_jobs() -> int:
    """Print every known job with live/pid state."""
    async def collect():
        out = []
        for store in _all_stores():
            out.extend(await store.list_jobs())
        return out
    jobs = asyncio.run(collect())
    if not jobs:
        console.print("No jobs found.")
        return 0
    for j in jobs:
        d = _find_job_dir(j.id)
        pid = read_pid(d) if d else None
        live = "🟢 running" if (pid and pid_alive(pid)) else ""
        console.print(
            f"[cyan]{j.id}[/cyan]  {j.name}  {j.status.value}  "
            f"{j.scanned_files}/{j.total_files} {live}"
        )
    return 0


def _kill(job_id: str, force: bool) -> int:
    """Drain (sentinel) or force-kill (SIGINT) a job."""
    job_dir = _find_job_dir(job_id)
    if job_dir is None:
        console.print(f"[red]Job not found:[/red] {job_id}")
        return 1
    if force:
        if force_kill(job_dir):
            console.print(f"[red]SIGINT sent[/red] to job {job_id} — janitor will checkpoint.")
            return 0
        console.print("[yellow]No live process found — touching CANCEL sentinel instead.[/yellow]")
    request_cancel(job_dir)
    console.print(
        f"🛑 Cancel requested for [cyan]{job_id}[/cyan] — in-flight batches finish, "
        "rest are skipped. Use [cyan]-f[/cyan] to force-kill if it doesn't stop."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch `rex jobs [kill <id> [-f|--force]]`."""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        return _list_jobs()
    if argv[0] == "kill" and len(argv) >= 2:
        return _kill(argv[1], force=any(a in {"-f", "--force"} for a in argv[2:]))
    console.print("[red]Usage:[/red] rex jobs | rex jobs kill <job_id> [-f]")
    return 1
