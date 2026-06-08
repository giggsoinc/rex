"""Secret I/O helpers for the Settings page.

Read masked values from environment; write new values to a project-local
.env.local without exposing existing secrets on screen.

Design:
  - read_masked(key)    → "sk-...XXXX" (shows last 4 chars; "" if unset)
  - write_secret(k, v)  → upserts into .env.local; never logs the value
  - list_known_keys()   → curated list of secret env-var names Rex uses
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["read_masked", "write_secret", "list_known_keys", "is_set"]

# Curated list — only secret-shaped env vars exposed in Settings UI
_KNOWN_SECRETS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "LANGCHAIN_API_KEY",
)

_ENV_FILE_DEFAULT = Path(".env.local")


def list_known_keys() -> list[str]:
    """Return the curated list of secret env vars Rex surfaces in the UI."""
    return list(_KNOWN_SECRETS)


def is_set(key: str) -> bool:
    """True if the env var is set to a non-empty value."""
    return bool((os.getenv(key) or "").strip())


def read_masked(key: str) -> str:
    """Return a masked representation of a secret (last 4 chars visible).

    "" if unset. Used to render Settings inputs without leaking the secret.
    """
    val = (os.getenv(key) or "").strip()
    if not val:
        return ""
    if len(val) <= 4:
        return "*" * len(val)
    return f"{'*' * 8}…{val[-4:]}"


def write_secret(
    key: str, value: str, env_path: Path | str = _ENV_FILE_DEFAULT,
) -> Path:
    """Upsert key=value into env_path. Creates the file if missing.

    The current process's os.environ is also updated so subsequent reads
    see the new value without a restart. Empty value removes the entry.

    Returns the env file path written.
    """
    path = Path(env_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""

    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if value == "":
        # Delete the entry
        new_text = pattern.sub("", existing).strip("\n") + "\n"
        os.environ.pop(key, None)
    else:
        escaped = value.replace("\n", "\\n").replace('"', '\\"')
        line = f'{key}="{escaped}"'
        if pattern.search(existing):
            new_text = pattern.sub(line, existing)
        else:
            new_text = existing + ("\n" if existing and not existing.endswith("\n") else "") + line + "\n"
        os.environ[key] = value

    path.write_text(new_text)
    return path
