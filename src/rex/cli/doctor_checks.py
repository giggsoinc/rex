"""Individual health checks for `rex doctor`.

Each check returns a CheckResult so the CLI can render a table + remediation.
Lives in its own module so doctor.py stays under the 150-line guard.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

__all__ = ["CheckResult", "ALL_CHECKS"]


@dataclass
class CheckResult:
    """One row in the doctor report."""

    name: str
    status: str  # green / amber / red
    detail: str
    fix: str = ""


def _has_binary(name: str) -> bool:
    """True if a binary is on PATH."""
    return shutil.which(name) is not None


def _check_libreoffice() -> CheckResult:
    """LibreOffice — needed for legacy .doc/.xls/.ppt extraction."""
    if _has_binary("soffice") or _has_binary("libreoffice"):
        return CheckResult("LibreOffice (soffice)", "green", "installed")
    return CheckResult(
        "LibreOffice (soffice)", "amber",
        "missing — legacy .doc/.xls/.ppt files will be skipped",
        "brew install --cask libreoffice   # macOS\n"
        "       apt install libreoffice          # Debian/Ubuntu",
    )


def _check_ollama() -> CheckResult:
    """Ollama — local LLM backend for default routing profile."""
    if not _has_binary("ollama"):
        return CheckResult(
            "Ollama", "red", "missing — local profile + balanced embed will fail",
            "brew install ollama   # macOS\n"
            "       curl -fsSL https://ollama.com/install.sh | sh   # Linux",
        )
    return CheckResult("Ollama", "green", "installed")


def _check_tesseract() -> CheckResult:
    """Tesseract OCR — offline OCR fallback."""
    if _has_binary("tesseract"):
        return CheckResult("Tesseract OCR", "green", "installed")
    return CheckResult(
        "Tesseract OCR", "amber",
        "missing — offline OCR unavailable (cloud Vision still works)",
        "brew install tesseract   # macOS",
    )


def _check_ffmpeg() -> CheckResult:
    """ffmpeg — video metadata extraction."""
    if _has_binary("ffmpeg"):
        return CheckResult("ffmpeg", "green", "installed")
    return CheckResult(
        "ffmpeg", "amber",
        "missing — .mp4/.mov metadata limited to filename signal",
        "brew install ffmpeg   # macOS",
    )


def _check_python_module(mod: str, label: str | None = None, *, red: bool = False) -> CheckResult:
    """Generic Python module check."""
    label = label or mod
    severity = "red" if red else "amber"
    try:
        __import__(mod)
        return CheckResult(label, "green", "installed")
    except ImportError as e:
        return CheckResult(label, severity, f"missing ({str(e)[:60]})", f"pip install {mod}")


ALL_CHECKS: list[Callable[[], CheckResult]] = [
    _check_ollama,
    _check_libreoffice,
    _check_tesseract,
    _check_ffmpeg,
    lambda: _check_python_module("litellm", "litellm (router)", red=True),
    lambda: _check_python_module("yaml", "pyyaml (routing config)", red=True),
    lambda: _check_python_module("magic", "python-magic (mime detect)"),
    lambda: _check_python_module("pdfplumber", "pdfplumber (PDF extract)"),
    lambda: _check_python_module("docx", "python-docx (.docx)"),
    lambda: _check_python_module("pptx", "python-pptx (.pptx)"),
    lambda: _check_python_module("openpyxl", "openpyxl (.xlsx)"),
    lambda: _check_python_module("lancedb", "lancedb (vectors)", red=True),
]
