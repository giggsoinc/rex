"""PreFlight checks — verify environment before scan.

All checks run in parallel where possible. Each check returns a CheckResult.
The overall PreFlightReport carries traffic-light status:
  - HARD_FAIL: cannot proceed (no disk, no Ollama, no destination)
  - SOFT_WARN: can proceed with degradation (no Gemini → no vision)
  - OK: green

User decides on SOFT_WARN unless intent.accept_soft_warnings=True.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from rex.config import Settings, VisionProvider, get_settings
from rex.preflight.intent import ScanIntent

console = Console()
logger = structlog.get_logger()


class CheckStatus(str, Enum):
    """Outcome of a single check."""

    OK = "ok"
    SOFT_WARN = "soft_warn"
    HARD_FAIL = "hard_fail"


@dataclass
class CheckResult:
    """Result of one PreFlight check."""

    name: str
    status: CheckStatus
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class PreFlightReport:
    """Aggregate PreFlight result."""

    results: list[CheckResult]
    overall: CheckStatus = CheckStatus.OK

    @property
    def hard_fails(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.HARD_FAIL]

    @property
    def soft_warns(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.SOFT_WARN]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.OK]

    def compute_overall(self) -> None:
        if any(r.status == CheckStatus.HARD_FAIL for r in self.results):
            self.overall = CheckStatus.HARD_FAIL
        elif any(r.status == CheckStatus.SOFT_WARN for r in self.results):
            self.overall = CheckStatus.SOFT_WARN
        else:
            self.overall = CheckStatus.OK


# --- Individual checks ---

async def check_ollama(settings: Settings, model_name: str) -> CheckResult:
    """Verify Ollama is reachable and the model is pulled."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.llm_endpoint}/api/tags")
        if r.status_code != 200:
            return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                               f"API returned {r.status_code}",
                               {"endpoint": settings.llm_endpoint})
        models = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(model_name.split(":")[0] in m for m in models):
            return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                               f"Model '{model_name}' not pulled. Available: {models[:5]}",
                               {"available": models, "needed": model_name})
        return CheckResult("Ollama", CheckStatus.OK,
                           f"Reachable, '{model_name}' available",
                           {"models_count": len(models)})
    except Exception as e:
        return CheckResult("Ollama", CheckStatus.HARD_FAIL,
                           f"Cannot reach Ollama: {str(e)[:120]}",
                           {"endpoint": settings.llm_endpoint})


async def check_embed_model(settings: Settings) -> CheckResult:
    """Verify embedding model is available."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.llm_endpoint}/api/tags")
        if r.status_code != 200:
            return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                               "Cannot list Ollama models for embeddings")
        models = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(settings.embed_model.split(":")[0] in m for m in models):
            return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                               f"Embedding model '{settings.embed_model}' not pulled",
                               {"needed": settings.embed_model})
        return CheckResult("Embeddings", CheckStatus.OK,
                           f"'{settings.embed_model}' ready")
    except Exception as e:
        return CheckResult("Embeddings", CheckStatus.HARD_FAIL,
                           f"Embed check failed: {str(e)[:120]}")


async def check_gemini(settings: Settings) -> CheckResult:
    """Verify Gemini API key (for vision)."""
    if settings.vision_provider == VisionProvider.NONE:
        return CheckResult("Gemini", CheckStatus.OK, "Vision disabled (skip)")
    if not settings.gemini_api_key:
        return CheckResult("Gemini", CheckStatus.SOFT_WARN,
                           "No Gemini key — image vision will be skipped",
                           {"fix": "Set GEMINI_API_KEY in .env to enable"})
    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        # Light test — just list models
        await asyncio.to_thread(client.models.list)
        return CheckResult("Gemini", CheckStatus.OK, "API key valid")
    except Exception as e:
        return CheckResult("Gemini", CheckStatus.SOFT_WARN,
                           f"Gemini key set but failed test: {str(e)[:80]}",
                           {"fix": "Verify GEMINI_API_KEY value"})


async def check_disk(source_path: str, output_path: str, estimated_bytes: int) -> CheckResult:
    """Free space at output destination must hold ≥2× source size."""
    try:
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(out.parent)
        needed = max(estimated_bytes * 2, 100 * 1024 * 1024)  # min 100MB headroom
        if usage.free < needed:
            return CheckResult("Disk", CheckStatus.HARD_FAIL,
                               f"Only {_human_size(usage.free)} free, need ≥{_human_size(needed)}",
                               {"free": usage.free, "needed": needed})
        if usage.free < needed * 2:
            return CheckResult("Disk", CheckStatus.SOFT_WARN,
                               f"Disk getting tight: {_human_size(usage.free)} free",
                               {"free": usage.free})
        return CheckResult("Disk", CheckStatus.OK,
                           f"{_human_size(usage.free)} free at output destination",
                           {"free": usage.free})
    except Exception as e:
        return CheckResult("Disk", CheckStatus.SOFT_WARN,
                           f"Disk check failed: {e}")


async def check_lancedb_writable(vector_path: str) -> CheckResult:
    """Vector store path must be writable."""
    try:
        p = Path(vector_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Test write
        test = p.parent / ".rex_write_test"
        test.write_text("ok")
        test.unlink()
        return CheckResult("VectorDB", CheckStatus.OK,
                           f"Writable at {p.parent}",
                           {"path": str(p)})
    except Exception as e:
        return CheckResult("VectorDB", CheckStatus.HARD_FAIL,
                           f"Cannot write to vector path: {e}",
                           {"path": vector_path})


def check_deps() -> CheckResult:
    """Check optional Python dependencies for richer extraction."""
    missing = []
    have = []
    try:
        import unstructured  # noqa: F401
        have.append("unstructured")
    except ImportError:
        missing.append("unstructured")
    try:
        import pdfplumber  # noqa: F401
        have.append("pdfplumber")
    except ImportError:
        missing.append("pdfplumber")
    try:
        import magic  # noqa: F401
        have.append("python-magic")
    except ImportError:
        missing.append("python-magic")

    if not have:
        return CheckResult("Extractors", CheckStatus.SOFT_WARN,
                           "No extraction libs installed — quality will degrade",
                           {"missing": missing, "fix": "pip install unstructured pdfplumber python-magic"})
    if missing:
        return CheckResult("Extractors", CheckStatus.SOFT_WARN,
                           f"Have: {', '.join(have)} | Missing: {', '.join(missing)}",
                           {"missing": missing})
    return CheckResult("Extractors", CheckStatus.OK, f"All available: {', '.join(have)}")


async def check_source(source_path: str) -> CheckResult:
    """Source folder readable + has files."""
    p = Path(source_path).expanduser()
    if not p.exists():
        return CheckResult("Source", CheckStatus.HARD_FAIL,
                           f"Source folder not found: {p}")
    if not p.is_dir():
        return CheckResult("Source", CheckStatus.HARD_FAIL,
                           f"Source is not a directory: {p}")
    if not os.access(p, os.R_OK):
        return CheckResult("Source", CheckStatus.HARD_FAIL,
                           f"Source not readable: {p}")
    return CheckResult("Source", CheckStatus.OK, f"Readable: {p}")


# --- Runner ---

async def run_preflight(
    intent: ScanIntent,
    source_path: str,
    output_path: str,
    vector_path: str,
    settings: Settings | None = None,
) -> PreFlightReport:
    """Run all PreFlight checks in parallel."""
    s = settings or get_settings()

    tasks = [
        check_ollama(s, intent.llm_model) if intent.llm_provider == "ollama" else _noop_check("LLM", "Using cloud LLM"),
        check_embed_model(s),
        check_gemini(s),
        check_disk(source_path, output_path, intent.estimated_total_bytes),
        check_lancedb_writable(vector_path),
        check_source(source_path),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    results = list(results) + [check_deps()]

    report = PreFlightReport(results=results)
    report.compute_overall()
    return report


async def _noop_check(name: str, msg: str) -> CheckResult:
    return CheckResult(name, CheckStatus.OK, msg)


# --- UI ---

def print_preflight_report(report: PreFlightReport) -> None:
    """Render the PreFlight report as a table."""
    table = Table(title="PreFlight Report", show_header=True, header_style="bold")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details", overflow="fold")
    for r in report.results:
        if r.status == CheckStatus.OK:
            status_col = "[green]✓ OK[/green]"
        elif r.status == CheckStatus.SOFT_WARN:
            status_col = "[yellow]⚠ WARN[/yellow]"
        else:
            status_col = "[red]✗ FAIL[/red]"
        table.add_row(r.name, status_col, r.message)
    console.print(table)


def confirm_proceed(report: PreFlightReport, intent: ScanIntent) -> bool:
    """Ask user to proceed if SOFT_WARNs exist. Hard fail blocks unconditionally."""
    if report.overall == CheckStatus.HARD_FAIL:
        console.print(f"\n[red bold]✗ {len(report.hard_fails)} hard failure(s). Cannot proceed.[/red bold]")
        for r in report.hard_fails:
            console.print(f"  [red]• {r.name}:[/red] {r.message}")
            if r.detail.get("fix"):
                console.print(f"    [dim]Fix: {r.detail['fix']}[/dim]")
        return False

    if report.overall == CheckStatus.SOFT_WARN:
        if intent.accept_soft_warnings:
            console.print("\n[yellow]⚠ Soft warnings present — proceeding (--soft mode).[/yellow]")
            for r in report.soft_warns:
                console.print(f"  [yellow]• {r.name}:[/yellow] {r.message}")
            return True

        console.print(f"\n[yellow]⚠ {len(report.soft_warns)} soft warning(s):[/yellow]")
        for r in report.soft_warns:
            console.print(f"  • {r.name}: {r.message}")
            if r.detail.get("fix"):
                console.print(f"    [dim]Fix: {r.detail['fix']}[/dim]")
        if not sys.stdin.isatty():
            console.print("[dim]Non-interactive — defaulting to 'no'. Pass --soft to auto-accept.[/dim]")
            return False
        return Confirm.ask("\nProceed anyway?", default=True)

    return True


def _human_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    for unit, div in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)]:
        if b < div * 1024:
            return f"{b / div:.1f} {unit}"
    return f"{b / (1024**4):.1f} TB"
