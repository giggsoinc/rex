"""Skip rule constants — patterns, dirs, sizes, non-processable extensions.

Lessons learned from real-world cluster-fuck scans:
  - Office leaves ~$lock files that crash extractors
  - macOS sprinkles .DS_Store, Thumbs.db
  - Random tmp/swap files have no semantic meaning
  - Huge files (videos, ISOs) blow embed context windows
"""

from __future__ import annotations


DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


# Patterns matched via fnmatch on filename (not full path)
DEFAULT_SKIP_PATTERNS: tuple[str, ...] = (
    # Office lock / temp files
    "~$*",
    ".~lock.*",
    "*.tmp",
    "*.temp",
    "*~",
    # macOS
    ".DS_Store",
    "._*",
    # Windows
    "Thumbs.db",
    "desktop.ini",
    "ehthumbs.db",
    # Editor swap
    ".*.swp",
    ".*.swo",
    "*.bak",
    # Cache / hidden Rex / Git
    ".cache",
    ".rex",
    # Version control
    ".gitignore",
    ".gitkeep",
)

# Directories to skip entirely during walk
DEFAULT_SKIP_DIRS: tuple[str, ...] = (
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".npm", ".yarn",
    ".venv", "venv", "env", ".env",
    ".raven", ".rex",
    ".DS_Store",
    ".cache", ".idea", ".vscode",
)

# Extensions that have no useful text content for the LLM router (binary blobs)
NON_PROCESSABLE_EXTS: tuple[str, ...] = (
    ".iso", ".dmg", ".vmdk", ".vdi",
    ".exe", ".msi", ".dll", ".so", ".dylib",
    ".pkg", ".deb", ".rpm",
    ".class", ".jar", ".war",
    ".pyc", ".pyo",
)
