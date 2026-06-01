"""Rex Projects — the unit of isolation.

Every scan belongs to a project. A project owns:
  - its own vector store (tagged with project name + creation timestamp)
  - its own job store (scan history)
  - its own output folder (organized files + catalog)
  - its own context (user-provided hints for the LLM router)
"""

from rex.projects.model import Project
from rex.projects.store import ProjectStore

__all__ = ["Project", "ProjectStore"]
