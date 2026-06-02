"""Skip rules — filename patterns + size limits.

Enum + dataclass + functions. The big constant tuples live in
``rex.utils.skip_constants`` (re-exported here for backwards compat).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rex.utils.skip_constants import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SKIP_DIRS,
    DEFAULT_SKIP_PATTERNS,
    NON_PROCESSABLE_EXTS,
)

__all__ = [
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_SKIP_DIRS",
    "DEFAULT_SKIP_PATTERNS",
    "NON_PROCESSABLE_EXTS",
    "SkipReason",
    "SkipRules",
    "should_skip",
    "is_skip_dir",
    "truncate_for_embedding",
]


class SkipReason(str, Enum):
    """Why a file was skipped."""

    NONE = "none"
    OFFICE_TEMP = "office_temp_file"
    OS_METADATA = "os_metadata_file"
    EDITOR_SWAP = "editor_swap_file"
    HIDDEN = "hidden_file"
    TOO_LARGE = "too_large"
    BINARY_BLOB = "non_processable_binary"
    CUSTOM_PATTERN = "matches_custom_pattern"
    INVALID_EXTENSION = "invalid_extension"


@dataclass
class SkipRules:
    """Configurable skip policy."""

    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    skip_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_PATTERNS))
    skip_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_SKIP_DIRS))
    skip_non_processable_binary: bool = True
    skip_hidden: bool = True
    extra_patterns: list[str] = field(default_factory=list)

    @classmethod
    def default(cls) -> "SkipRules":
        """Standard production defaults."""
        return cls()

    @classmethod
    def permissive(cls) -> "SkipRules":
        """Don't skip binaries (slower but more complete)."""
        return cls(skip_non_processable_binary=False, skip_hidden=False)

    def all_patterns(self) -> list[str]:
        """Combined skip patterns."""
        return list(self.skip_patterns) + list(self.extra_patterns)


def should_skip(path: str | Path, rules: SkipRules | None = None) -> SkipReason:
    """Return the reason this file should be skipped, or SkipReason.NONE.

    Args:
        path: File path.
        rules: Skip rules (defaults to SkipRules.default()).

    Returns:
        SkipReason — NONE means do not skip.
    """
    rules = rules or SkipRules.default()
    p = Path(path)
    name = p.name
    ext = p.suffix.lower()

    # Hidden (dotfile) — but allow some known-good ones
    if rules.skip_hidden and name.startswith("."):
        # Exception: .md, .txt, .json hidden files might be intentional notes
        if ext not in {".md", ".txt", ".json", ".yaml", ".yml"}:
            return SkipReason.HIDDEN

    # Pattern matching
    for pattern in rules.all_patterns():
        if fnmatch.fnmatch(name, pattern):
            # Categorize by pattern
            if pattern.startswith("~$") or pattern.startswith(".~lock"):
                return SkipReason.OFFICE_TEMP
            if name in {".DS_Store", "Thumbs.db", "desktop.ini", "ehthumbs.db"} or name.startswith("._"):
                return SkipReason.OS_METADATA
            if pattern.endswith(".swp") or pattern.endswith(".swo") or pattern.endswith("~") or pattern.endswith(".bak"):
                return SkipReason.EDITOR_SWAP
            if "*.tmp" in pattern or "*.temp" in pattern:
                return SkipReason.OFFICE_TEMP
            return SkipReason.CUSTOM_PATTERN

    # Non-processable binary extensions
    if rules.skip_non_processable_binary and ext in NON_PROCESSABLE_EXTS:
        return SkipReason.BINARY_BLOB

    # Size limit
    try:
        size = p.stat().st_size
        if size > rules.max_file_size_bytes:
            return SkipReason.TOO_LARGE
    except OSError:
        # Can't stat — let scanner handle it
        pass

    return SkipReason.NONE


def is_skip_dir(name: str, rules: SkipRules | None = None) -> bool:
    """Should this directory be skipped during walk?"""
    rules = rules or SkipRules.default()
    return name in rules.skip_dirs or (name.startswith(".") and name != ".")


def truncate_for_embedding(text: str, max_chars: int = 1000) -> str:
    """Truncate text so it fits all-minilm's 256-token context (~1000 chars).

    Prefer truncating at sentence/paragraph boundaries when possible.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    # Try to truncate at last newline before limit
    cut = text[:max_chars]
    last_break = max(cut.rfind("\n\n"), cut.rfind("\n"), cut.rfind(". "))
    if last_break > max_chars * 0.5:
        return text[:last_break]
    return cut
