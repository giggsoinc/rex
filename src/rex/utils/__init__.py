"""Cross-cutting utilities — skip rules, truncation, sizing."""

from rex.utils.skip_rules import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SKIP_PATTERNS,
    SkipReason,
    SkipRules,
    should_skip,
)

__all__ = [
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_SKIP_PATTERNS",
    "SkipReason",
    "SkipRules",
    "should_skip",
]
