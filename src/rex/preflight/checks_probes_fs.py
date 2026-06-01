"""Filesystem + dependency PreFlight probes."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from rex.preflight.checks_models import CheckResult, CheckStatus


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


async def _noop_check(name: str, msg: str) -> CheckResult:
    return CheckResult(name, CheckStatus.OK, msg)


def _human_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    for unit, div in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)]:
        if b < div * 1024:
            return f"{b / div:.1f} {unit}"
    return f"{b / (1024**4):.1f} TB"
