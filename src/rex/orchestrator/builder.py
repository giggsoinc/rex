"""Pipeline builder — wires the standard Rex pipeline.

Two entry points:
  build_default_pipeline(settings)   — global default (legacy, no project)
  build_project_pipeline(project)    — project-isolated (preferred)

Project pipelines get their own LanceDB, JobStore, output path —
nothing crosses between projects.
"""

from __future__ import annotations

import structlog

from rex.agents.classifier_router import ClassifierRouter
from rex.agents.organizer import LocalOrganizer
from rex.agents.router import LLMRouter
from rex.agents.scanner import LocalScanner
from rex.ml.classifier import get_classifier
from rex.ml.classifier.base import Classifier
from rex.projects.context_store import ContextStore
from rex.config import Settings, VectorStoreType, get_settings
from rex.ml.provider import ModelProvider
from rex.ml.vision import VisionEngine
from rex.orchestrator.pipeline import RexPipeline
from rex.orchestrator.state import JobStore
from rex.projects.model import Project
from rex.vectorstore import get_vector_store
from rex.vectorstore.lancedb_store import LanceDBStore

logger = structlog.get_logger()


def build_default_pipeline(settings: Settings | None = None) -> RexPipeline:
    """Legacy: construct a Rex pipeline using global settings (no project isolation).

    Prefer build_project_pipeline() for new code.
    """
    s = settings or get_settings()
    model_provider = ModelProvider(s)
    vision_engine = VisionEngine(s)
    vector_store = get_vector_store(s)
    job_store = JobStore(base_path="~/rex-data/jobs")

    scanner = LocalScanner(model_provider, vision_engine, vector_store, job_store, s)
    router = LLMRouter(model_provider, s)
    organizer = LocalOrganizer(job_store, s)

    return RexPipeline(scanner, router, organizer, vector_store, job_store, s)


def build_classifier_pipeline(
    classifier_name: str = "knn",
    classifier: Classifier | None = None,
    settings: Settings | None = None,
    **classifier_kwargs,
) -> RexPipeline:
    """Construct a pipeline that uses the plug-and-play classifier module.

    Args:
        classifier_name: name from registry (knn / llm_zero_shot / ensemble).
                         Ignored if `classifier` is provided directly.
        classifier:      pre-built Classifier instance (preferred for ensemble).
        settings:        Rex Settings; defaults to get_settings().
        **classifier_kwargs: forwarded to the registry factory when building by name.

    The resulting pipeline routes through ClassifierRouter instead of LLMRouter,
    giving real ML-driven confidence and an easy retrain path via the lifecycle
    helpers in rex.ml.classifier.lifecycle.
    """
    s = settings or get_settings()
    model_provider = ModelProvider(s)
    vision_engine = VisionEngine(s)
    vector_store = get_vector_store(s)
    job_store = JobStore(base_path="~/rex-data/jobs")

    clf = classifier or get_classifier(classifier_name, **classifier_kwargs)
    scanner = LocalScanner(model_provider, vision_engine, vector_store, job_store, s)
    router = ClassifierRouter(classifier=clf, settings=s)
    organizer = LocalOrganizer(job_store, s)
    logger.info("classifier_pipeline_built", classifier=clf.name)
    return RexPipeline(scanner, router, organizer, vector_store, job_store, s)


def build_project_pipeline(project: Project, settings: Settings | None = None) -> RexPipeline:
    """Construct an isolated pipeline for a specific Project.

    Each project gets:
      - Its own LanceDB at project.vector_path (tagged with name + timestamp)
      - Its own JobStore at project.jobs_path
      - Its own output at project.output_path
      - Its context fed into the LLM router's system prompt
    """
    s = settings or get_settings()
    project.ensure_dirs()

    # Per-project vector store
    vector_store = LanceDBStore(db_path=project.vector_path, dim=s.embed_dim)

    # Per-project job store
    job_store = JobStore(base_path=project.jobs_path)

    # Shared model + vision (one Ollama server, one Gemini)
    model_provider = ModelProvider(s)
    vision_engine = VisionEngine(s)

    # Build agents with project-aware components
    scanner = LocalScanner(model_provider, vision_engine, vector_store, job_store, s)

    # Router receives project context to refine the system prompt
    router = LLMRouter(model_provider, s)
    router.project_context = project.context
    router.taxonomy_hints = list(project.taxonomy_hints)
    router.tag_vocabulary = list(project.tag_vocabulary)

    organizer = LocalOrganizer(job_store, s)

    pipeline = RexPipeline(scanner, router, organizer, vector_store, job_store, s)
    # Stamp the pipeline with project metadata for downstream consumers
    pipeline.project_name = project.name
    pipeline.project_output_path = project.output_path

    # Load BusinessContext if the project has one — promotes Stage 3 to SortEngine.
    # Looks for .raven/business_context.json under the project root (and CWD).
    ctx = ContextStore().get_for_project(project.root_path) or ContextStore().get_for_project()
    if ctx is not None and ctx.domains:
        pipeline.business_context = ctx
        logger.info("project_pipeline_sort_enabled", name=project.name, domains=ctx.domains)
    else:
        logger.info("project_pipeline_legacy_organize", name=project.name)

    logger.info(
        "project_pipeline_built",
        name=project.name,
        vector=project.vector_path,
        jobs=project.jobs_path,
        output=project.output_path,
    )
    return pipeline
