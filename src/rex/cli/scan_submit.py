"""`rex scan --bg` — submit a scan to the background and return immediately.

Spawns the real scan as a detached child process (own session, headless),
records its PID for kill/crash detection, and prints toast-style guidance:
the Streamlit link to follow progress and how to kill the job.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from rex.config import get_settings
from rex.orchestrator.job_control import clear_cancel, job_dir_for, write_pid
from rex.projects.model import Project

console = Console()


def submit_background(
    src_path: Path, project: Project, *, workers: int, mode: str,
    soft: bool, output_override: str | None,
) -> int:
    """Detach the scan, print toasts + follow link, exit immediately."""
    job_dir = job_dir_for(project.jobs_path, str(src_path))
    job_dir.mkdir(parents=True, exist_ok=True)
    clear_cancel(job_dir)
    log_file = job_dir / "scan.log"

    cmd = [
        sys.executable, "-m", "rex.cli.main", "scan", str(src_path),
        "--project", project.name, "--workers", str(workers),
        "--mode", mode, "-y", "--fg",  # child must run inline, not re-submit
    ]
    if soft:
        cmd.append("--soft")
    if output_override:
        cmd += ["--output", output_override]

    with log_file.open("a") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,  # survives this terminal closing
        )
    write_pid(job_dir, proc.pid)

    job_id = job_dir.name
    console.print(f"🚀 [bold green]Scan submitted to background[/bold green] — job [cyan]{job_id}[/cyan] (pid {proc.pid})")
    ui_url = get_settings().ui_url
    console.print(f"📊 Follow live: [link={ui_url}]{ui_url}[/link]  (Jobs page)")
    console.print("⚠️  [yellow]Please don't shut down this machine until the job completes.[/yellow]")
    console.print(f"🪵 Logs: [dim]{log_file}[/dim]")
    console.print(f"🛑 Kill anytime: [cyan]rex jobs kill {job_id}[/cyan]  (or the ⏹ button in the UI)")
    return 0
