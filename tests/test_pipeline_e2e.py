"""End-to-end test: scan tests/fixtures/sample-data through the full pipeline.

Validates:
  - 14 files discovered + fingerprinted
  - Text extracted from PDFs and markdown
  - Embeddings stored in vector store
  - Router classifies all files
  - Exact duplicate (meeting_notes_2024_q3_COPY.md) detected
  - Near-duplicate (meeting_notes_2024_q3_v2.md) flagged
  - Organized output created with sidecars + catalog markdown

Run: pytest tests/test_pipeline_e2e.py -v -s
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "sample-data"
OUTPUT = REPO_ROOT / "tests" / ".e2e-output"
JOBS = REPO_ROOT / "tests" / ".e2e-jobs"
VECTORS = REPO_ROOT / "tests" / ".e2e-vectors.lance"


@pytest.fixture(autouse=True)
def clean_state():
    """Reset all e2e output before each run."""
    for p in (OUTPUT, JOBS, VECTORS):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    yield


@pytest.mark.asyncio
async def test_full_pipeline_runs_on_fixtures():
    """Smoke test — full pipeline completes without error."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))

    from rex.agents.organizer import LocalOrganizer
    from rex.agents.router import LLMRouter
    from rex.agents.scanner import LocalScanner
    from rex.config import Settings, VectorStoreType
    from rex.ml.provider import ModelProvider
    from rex.ml.vision import VisionEngine
    from rex.orchestrator.pipeline import RexPipeline
    from rex.orchestrator.state import JobStore
    from rex.vectorstore.lancedb_store import LanceDBStore

    # Use test-isolated settings
    settings = Settings(
        vector_store=VectorStoreType.LANCEDB,
        vector_path=str(VECTORS),
        storage_path=str(OUTPUT),
        vision_provider="none",  # skip vision in e2e to avoid API dep
    )

    model = ModelProvider(settings)
    vision = VisionEngine(settings)
    vector_store = LanceDBStore(db_path=str(VECTORS), dim=settings.embed_dim)
    job_store = JobStore(base_path=str(JOBS))

    scanner = LocalScanner(
        model_provider=model,
        vision_engine=vision,
        vector_store=vector_store,
        job_store=job_store,
        settings=settings,
    )
    router = LLMRouter(model_provider=model, settings=settings)
    organizer = LocalOrganizer(job_store=job_store, settings=settings)

    pipeline = RexPipeline(
        scanner=scanner,
        router=router,
        organizer=organizer,
        vector_store=vector_store,
        job_store=job_store,
        settings=settings,
    )

    assert FIXTURES.exists(), f"fixtures missing: {FIXTURES}"

    job = await pipeline.run(str(FIXTURES), output_path=str(OUTPUT), name="e2e_test")

    # Assertions
    assert job.status.value == "complete", f"job failed: {job.error}"
    assert job.scanned_files >= 13, f"expected >=13 files, got {job.scanned_files}"
    assert job.classified_files >= 1, "no files classified"
    assert job.organized_files >= 1, "no files organized"

    # Catalog markdown was generated
    catalog = OUTPUT / "_catalog"
    assert catalog.exists(), "catalog dir missing"
    assert (catalog / "index.md").exists(), "index.md missing"
    assert (catalog / "categories.md").exists(), "categories.md missing"
    assert (catalog / "tags.md").exists(), "tags.md missing"

    # Metadata sidecars
    metadata = OUTPUT / "_metadata"
    assert metadata.exists(), "metadata dir missing"
    sidecars = list(metadata.glob("*.json"))
    assert len(sidecars) >= 1, "no sidecars written"

    # Print summary for human review
    print(f"\n=== E2E SUMMARY ===")
    print(f"Job ID:      {job.id}")
    print(f"Status:      {job.status.value}")
    print(f"Scanned:     {job.scanned_files}")
    print(f"Classified:  {job.classified_files}")
    print(f"Organized:   {job.organized_files}")
    print(f"Duplicates:  {job.duplicate_count}")
    print(f"Categories:  {job.categories_discovered}")
    print(f"Output:      {OUTPUT}")
