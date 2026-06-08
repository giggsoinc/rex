# Implementation Guide

For developers building on, extending, or contributing to Rex.

---

## Repo Layout

```
src/rex/
├── agents/                 the ML agents (scanner, router, organizer, sorter)
│   ├── scanner*.py             reads files → FileRecord + embedding
│   ├── router*.py              LLM-based classifier (legacy path)
│   ├── classifier_router.py    plug-in classifier path
│   ├── organizer*.py           legacy organizer
│   └── sort_engine*.py         new SortEngine + 12-bucket taxonomy
│
├── ml/
│   ├── provider.py             unified LLM client (Ollama, Gemini, Claude, …)
│   ├── vision.py               Gemini vision client
│   └── classifier/             plug-and-play classifier module
│       ├── base.py             Classifier Protocol + Prediction
│       ├── registry.py         @register_classifier decorator
│       ├── algorithms/         knn · llm_zero_shot · ensemble (+ slots for more)
│       └── lifecycle/          drift_detector · train · eval
│
├── models/
│   ├── schemas.py              core Pydantic models
│   └── business_context.py     BusinessContext + ModelProfile
│
├── orchestrator/
│   ├── pipeline.py             RexPipeline (Scanner → Router → Organizer)
│   ├── pipeline_stages.py      run_route_stage + run_organize_stage
│   ├── pipeline_sort.py        run_sort_stage (two-phase path)
│   ├── builder.py              build_default_pipeline + build_classifier_pipeline
│   └── state.py                JobStore — JSON-on-disk job state
│
├── projects/
│   ├── store.py                ProjectStore
│   └── context_store.py        BusinessContext persistence
│
├── mcp/                        MCP server (FastMCP)
│   ├── server.py
│   ├── tools_jobs.py · tools_projects.py · tools_query.py · tools_review.py
│
├── cli/
│   ├── main.py                 dispatcher
│   ├── init.py · scan.py · serve.py · project.py · tail.py
│
├── ui/                         Streamlit pages
│   ├── app.py
│   ├── pages_onboard.py · pages_scan.py · pages_review.py
│   ├── pages_misc.py · pages_browse.py · pages_settings.py
│   ├── review_queue.py · state.py · secrets_io.py
│
├── vectorstore/                LanceDB + pgvector backends
├── plugins/                    pluggable filesystem (local + future S3 / GCS)
└── config.py                   Settings (env-driven, pydantic-settings)
```

---

## Coding Conventions

| Rule | Why |
|---|---|
| **≤150 lines per file** | Enforced by Raven pre-commit guard |
| Type hints required | mypy strict |
| Docstrings on public surfaces | Style guard |
| `from __future__ import annotations` everywhere | Forward-ref safety |
| No inline SQL in app code | DB guard |
| Snake-case module + function names | PEP 8 |
| `__all__` exports public symbols | Avoid `*` import surprises |

If a file grows past 150 lines, split by responsibility (the existing
`sort_engine_*` split is the model).

---

## Adding a New Classifier Algorithm

1. **Create** `src/rex/ml/classifier/algorithms/<name>.py`:

```python
"""Brief 1-line + when to use."""

from __future__ import annotations
from typing import Any
import structlog

from rex.ml.classifier.base import Prediction
from rex.ml.classifier.registry import register_classifier

logger = structlog.get_logger()

__all__ = ["MyClassifier", "make_my"]


class MyClassifier:
    name = "my_algo"

    def __init__(self, **kwargs) -> None:
        ...

    def fit(self, examples: list[tuple[list[float], str]]) -> None:
        ...

    def predict(self, embedding: list[float], **kwargs: Any) -> Prediction:
        return Prediction(category="...", confidence=0.9, source=self.name)

    def explain(self, embedding: list[float]) -> dict[str, Any]:
        return {"name": self.name}


@register_classifier("my_algo")
def make_my(**kwargs: Any) -> MyClassifier:
    return MyClassifier(**kwargs)
```

2. **Register** by adding to `src/rex/ml/classifier/algorithms/__init__.py`:

```python
from rex.ml.classifier.algorithms import my_algo  # noqa: F401
```

3. **Use**:
```python
from rex.ml.classifier import get_classifier
clf = get_classifier("my_algo", k=5)
```

The pipeline doesn't change. Pass it to `build_classifier_pipeline` via the
`classifier=` arg.

---

## Adding a New MCP Tool

In `src/rex/mcp/tools_review.py` (or a new `tools_<area>.py`):

```python
def register_my_tools(app: Any) -> None:
    @app.tool()
    async def rex_my_tool(arg: str) -> dict[str, Any]:
        """Brief description (used as MCP tool description)."""
        return {"ok": True, "echo": arg}
```

Then in `server.py`:
```python
from rex.mcp.tools_my import register_my_tools
...
register_my_tools(app)
```

Tools must return JSON-serializable values. Errors raise as exceptions.

---

## Adding a New Streamlit Page

1. Create `src/rex/ui/pages_<name>.py` with a `page_<name>()` function
2. Wire it into `src/rex/ui/app.py` `PAGES` dict
3. Keep the page under 150 lines — split logic into helper modules
4. Use `st.session_state` for cross-page data

Pattern from `pages_review.py`:
```python
def page_my() -> None:
    """Entry point."""
    st.title("📥 My Page")
    # Use helpers, not inline business logic
    items = _load_items()
    _render(items)
```

---

## Extending the Schema

When you add a field to `ScanJob`, `FileDecision`, or `FileRecord`:

1. Edit `src/rex/models/schemas.py`
2. **Add a default value** — backward-compat with old `job.json` files
3. Run `python3 -c "from rex.models.schemas import ScanJob; print(ScanJob(...).model_dump_json())"` to validate
4. Watch the line count — `schemas.py` is at the 150 ceiling; split if needed

Pattern for splitting (as `business_context.py` did): a new module under
`src/rex/models/` that schemas.py re-imports.

---

## Job Lifecycle Hooks

Want to do something every time a job finishes? Three options:

| Option | Where | When |
|---|---|---|
| **Pipeline post-hook** | Subclass `RexPipeline.run` | End of every scan |
| **Stop hook** (Raven) | `~/.claude/scripts/` | End of every Claude session |
| **Drift cron** | external scheduler | Periodic |

For "fire on every job complete" the cleanest is to wrap `RexPipeline.run`:

```python
class MyPipeline(RexPipeline):
    async def run(self, source_path, output_path=None, name=""):
        job = await super().run(source_path, output_path, name)
        await self.on_complete(job)
        return job

    async def on_complete(self, job):
        ...  # webhook, notification, retrain trigger, …
```

---

## Testing Patterns

Tests live in `tests/`. Use `pytest` + `pytest-asyncio` (already in dev deps).

### Unit test a classifier
```python
import pytest
from rex.ml.classifier import get_classifier

def test_knn_basic():
    clf = get_classifier("knn", k=3)
    clf.fit([
        ([1.0, 0.0], "A"),
        ([0.9, 0.1], "A"),
        ([0.0, 1.0], "B"),
    ])
    pred = clf.predict([0.95, 0.05])
    assert pred.category == "A"
    assert pred.confidence > 0.5
```

### Integration test the sort engine
```python
@pytest.mark.asyncio
async def test_sort_engine_routes_low_conf_to_review(tmp_path):
    ctx = BusinessContext(business="t", domains=["X"], confidence_threshold=0.7)
    rec = FileRecord(...)
    dec = FileDecision(category="X", confidence=0.5, ...)
    engine = SortEngine()
    sort = await engine.place(rec, dec, ctx, tmp_path)
    assert "_Review" in str(sort.destination)
```

### E2E pipeline smoke
See the inline `python3 << EOF` blocks committed in the conversation
history for end-to-end pipeline runs against `~/rex-test`.

---

## Working with Raven Guards

Every commit triggers Raven pre-commit hooks:

| Stage | Blocking? | What it checks |
|---|---|---|
| Publisher | warn | framework dirs not tracked |
| Manifest | block | `.raven/manifest.json` valid |
| Secrets | block | no `OPENAI_API_KEY=sk-...` in code |
| Library CVE | warn | known-vuln dep lookup |
| Style | block on hard | 150-line cap; warn on missing docstrings / hints |
| Guard | block | no `.raven/` deletions |
| DB Guard | block | no inline SQL in non-SQL files |

If a hook blocks, fix the violation and recommit — never `--no-verify`.

---

## Working with Andie

Strategic / planning work goes through Andie. Three modes you'll meet:
- 📘 **Deep** — understanding
- 🎭 **Drama** — comparing options
- 🔄 **Kaizen** — improving a recurring failure
- 🚨 **War** — incident triage

Brownfield bug? Use `andie-jr` directly:
```
/andie-jr   "the scan stopped at file 108, no progress for 10 min"
```

Andie produces a plan; specialists execute. Andie itself doesn't write
code (it hands off).

---

## Deployment Modes

| Mode | Vector store | LLM | Use |
|---|---|---|---|
| **LOCAL_ONLY** | LanceDB | Ollama only | Default; privacy-first |
| **BALANCED** | LanceDB | Gemini Flash + Ollama | Cheap + fast cloud assist |
| **PREMIUM** | LanceDB / pgvector | Claude / GPT-4 | Best quality, highest cost |
| **CUSTOM** | Anything | Per-stage user picks | Power users |

Switch in **⚙️ Settings → 🧠 Classifier** (Streamlit) or via BusinessContext
`model_profile` field.

---

## Performance Targets

| Stage | Per-file | 1,800-file folder |
|---|---|---|
| Scan + embed (all-minilm) | ~50 ms | 1.5 min |
| Vision describe (Gemini Flash) | ~400 ms | 12 min |
| LLM classify (qwen3:8b) | ~1 s | 30 min |
| kNN classify | ~5 ms | 9 sec |
| Sort + copy | ~5 ms + disk I/O | 5-10 min |
| Index write | <1 sec | <1 sec |

**Total ~17 GB / 1,800 files:**
- LLM-per-file: ~45-60 min
- Classifier (kNN ensemble): ~15-25 min

---

## What's NOT Built (PRs Welcome)

| Area | Status |
|---|---|
| BERTopic algorithm | Slot open in registry |
| SetFit algorithm | Slot open in registry |
| GraphRAG entity extraction | Phase 2 — separate work |
| Drift detector scheduler | Library exists, no cron |
| Active learning sampler | Designed, not built |
| Per-domain classifier config YAML | Designed, not parsed yet |
| Multi-modal CLIP/CLAP | Embedder slot designed |
| Auto-retrain on N-labels | Bootstrap exists; no trigger |

---

## Where to Ask

- Architectural decision → invoke `andie` (Drama mode) or `andie-guru`
- Bug → invoke `andie-jr`
- ML design → invoke `aiml-specialist` (Raven advisory)
- DB design → invoke `db-specialist` (Raven advisory)
- See `docs/diagrams/classification-pipeline.html` for the full pipeline diagram
