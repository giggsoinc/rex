"""Path safety guard — catches common config typos before they hit the FS.

Use case: user types REX_VECTOR_PATH=/GG_Graph (missing ~ before /) and Rex
silently tries to write at filesystem root. macOS's SIP makes / read-only, so
the open fails with a cryptic 'Read-only file system' error.

This guard catches the typo class up-front and explains the fix.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["PathConfigError", "validate_writable_path"]

# macOS / Linux dirs that are usually read-only or off-limits.
# NB: "/" is intentionally excluded — every absolute path is inside it,
#     so checking membership would false-positive on /Users/... etc.
#     Shallow-root paths like /GG_Graph are caught by _is_shallow_root_path.
_PROTECTED_ROOTS = {
    "/System", "/usr", "/bin", "/sbin", "/etc", "/var",
    "/Library", "/Applications", "/dev", "/cores",
    # /private is the macOS backing for /tmp and /var — allow /private/tmp
    # /Volumes is allowed for mounted drives — handled inside _is_inside_protected
}


class PathConfigError(ValueError):
    """Raised when a configured path is unwritable or suspicious."""


def _is_shallow_root_path(path: Path) -> bool:
    """True if the path is `/foo` (one segment under filesystem root).

    Almost always a typo — user meant ~/foo or /Users/<name>/foo.
    """
    parts = path.parts
    # parts[0] is "/" on macOS/Linux; a real user path has many parts
    return len(parts) == 2 and parts[0] in {"/", "\\"}


def _is_inside_protected(path: Path) -> str | None:
    """Return the protected ancestor if path lands inside it, else None."""
    for prot in _PROTECTED_ROOTS:
        prot_path = Path(prot).resolve()
        try:
            path.relative_to(prot_path)
            # OK if it's literally under /Volumes/MyDrive (mounted)
            if str(prot_path) == "/Volumes" and len(path.parts) >= 3:
                return None
            return str(prot_path)
        except ValueError:
            continue
    return None


def validate_writable_path(raw: str | Path, *, field: str = "path") -> Path:
    """Resolve + validate that a configured path is safely writable.

    Args:
        raw:   the path as configured (may have ~ to expand)
        field: name shown in error messages (e.g. 'REX_VECTOR_PATH')

    Returns:
        The resolved Path.

    Raises:
        PathConfigError with a clear remediation message if the path is
        shallow under root, inside a protected dir, or empty.
    """
    if not raw or str(raw).strip() == "":
        raise PathConfigError(f"{field} is empty — set it in .env.local")

    resolved = Path(raw).expanduser().resolve()

    if _is_shallow_root_path(resolved):
        raise PathConfigError(
            f"{field}={raw!r} resolves to {resolved} — a single-segment path "
            f"directly under filesystem root. This is almost always a typo. "
            f"Did you mean ~{raw} (under your home) or "
            f"/Users/$USER{raw} (explicit absolute)?"
        )

    protected = _is_inside_protected(resolved)
    if protected:
        raise PathConfigError(
            f"{field}={raw!r} resolves to {resolved}, inside the system-protected "
            f"dir {protected}. macOS SIP blocks writes here. Use a path under "
            f"your home directory instead (e.g. ~/rex-data/...)."
        )

    return resolved
