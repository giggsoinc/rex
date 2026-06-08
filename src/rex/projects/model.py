"""Project Pydantic model — the named, isolated unit of organization."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT_DEFAULT = Path("~/rex-data/projects").expanduser()
PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class Project(BaseModel):
    """A Rex project — isolated context for one user's domain of files.

    Naming: lowercase, hyphens/underscores, no spaces (filesystem-safe).
    Vector store path is tagged at creation with project name + UTC timestamp
    so collections are uniquely identifiable and future re-creates don't clash.
    """

    name: str = Field(description="Project name (filesystem-safe slug)")
    context: str = Field(default="", description="Free-text description for LLM router prompts")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Storage paths — all under PROJECT_ROOT_DEFAULT/{name}/ by default
    root_path: str = Field(default="", description="Project root folder")
    vector_path: str = Field(default="", description="LanceDB path — tagged with name + timestamp")
    jobs_path: str = Field(default="", description="JobStore base path")
    output_path: str = Field(default="", description="Where organized output goes")

    # Optional source binding — if set, scan with no folder arg uses this
    default_source: Optional[str] = None

    # LLM hints — feed into router prompt as system context
    taxonomy_hints: list[str] = Field(default_factory=list)
    tag_vocabulary: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not PROJECT_NAME_RE.match(v):
            raise ValueError(
                "Project name must be lowercase, start with letter/digit, "
                "and contain only letters, digits, hyphens, underscores (max 64 chars)"
            )
        return v

    @classmethod
    def new(
        cls,
        name: str,
        context: str = "",
        root: Path | str | None = None,
        default_source: str | None = None,
    ) -> "Project":
        """Construct a Project with auto-populated paths and tagged vector store.

        Vector path pattern:
            <root>/<name>/vectors_<name>_<UTC YYYYMMDD_HHMMSS>.lance/
        """
        root_path = Path(root).expanduser().resolve() if root else PROJECT_ROOT_DEFAULT / name
        root_path = root_path if not root else root_path
        if not root:
            root_path = PROJECT_ROOT_DEFAULT / name

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        vector_dir = root_path / f"vectors_{name}_{timestamp}.lance"
        jobs_dir = root_path / "jobs"

        # Output path honors REX_STORAGE_PATH env var if set (with /{name} suffix
        # to keep multiple projects isolated). Falls back to <root>/output.
        import os
        storage_root = os.environ.get("REX_STORAGE_PATH", "").strip()
        if storage_root:
            output_dir = Path(storage_root).expanduser().resolve() / name
        else:
            output_dir = root_path / "output"

        return cls(
            name=name,
            context=context,
            root_path=str(root_path),
            vector_path=str(vector_dir),
            jobs_path=str(jobs_dir),
            output_path=str(output_dir),
            default_source=default_source,
        )

    def ensure_dirs(self) -> None:
        """Create all project directories if missing."""
        for p in (self.root_path, self.jobs_path, self.output_path):
            Path(p).expanduser().mkdir(parents=True, exist_ok=True)
        # Vector path parent only; LanceDB creates the .lance dir itself
        Path(self.vector_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    def meta_path(self) -> Path:
        """Path to project.json metadata file."""
        return Path(self.root_path).expanduser() / "project.json"
