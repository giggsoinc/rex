"""Dotenv discovery — locate .env / .env.local regardless of CWD."""

from __future__ import annotations

import os
from pathlib import Path


def find_env_files() -> list[str]:
    """Locate .env / .env.local regardless of the current working directory.

    Rex is often launched from a folder other than its repo (e.g. via a
    pip-installed `rex` command). Relative dotenv paths break in that case,
    so we search a deterministic chain and return every file found.

    Search order (highest priority first; loaded with override=False so the
    earliest entry for a given key wins):
      1. $REX_ENV_FILE (explicit override)
      2. Current working directory
      3. Repo root (walk up from this module for pyproject.toml/.env.local)
      4. ~/.rex/  (user-global config)
    """
    found: list[str] = []

    # 1. Explicit override
    explicit = os.environ.get("REX_ENV_FILE")
    if explicit and Path(explicit).expanduser().exists():
        found.append(str(Path(explicit).expanduser()))

    # Candidate directories, in priority order
    dirs: list[Path] = [Path.cwd()]

    # Repo root — walk up from this file
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".env.local").exists():
            dirs.append(parent)
            break

    # User-global config dir
    dirs.append(Path.home() / ".rex")

    # Collect .env.local then .env in each dir (REX_* config wins over project .env)
    for d in dirs:
        for name in (".env.local", ".env"):
            p = d / name
            if p.exists() and str(p) not in found:
                found.append(str(p))

    return found
