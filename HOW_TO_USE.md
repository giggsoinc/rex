# How to Use Rex

Task-oriented playbook. Pick the workflow you need.

> **Two surfaces, one backend.** Streamlit UI and `rex` CLI hit the same code
> path. Use whichever you prefer; they don't conflict.

---

## Table of Contents

- [First run (10 min)](#first-run-10-min)
- [Scan a folder](#scan-a-folder)
- [Triage with HITL Review](#triage-with-hitl-review)
- [Search your knowledge base](#search-your-knowledge-base)
- [Use Rex from Claude (MCP)](#use-rex-from-claude-mcp)
- [Watch a running job](#watch-a-running-job)
- [Kill / resume a scan](#kill--resume-a-scan)
- [Backup & restore](#backup--restore)
- [Change settings](#change-settings)
- [Switch classifier algorithm](#switch-classifier-algorithm)

---

## First Run (10 min)

```bash
# 1. Install
git clone https://github.com/giggsoinc/rex.git
cd rex
pip install -e .

# 2. Pick deployment + vector store (one-time)
rex init

# 3. Start the UI
streamlit run src/rex/ui/app.py
# → http://localhost:8501
```

In the browser:

1. **🚀 Onboard**
   - Business description (1 sentence)
   - Domains (e.g. `Marketing, Sales, Strategy, Brand`)
   - Confidence threshold (default 0.7)
   - Model profile: **Balanced** is the right default
2. **📁 Scan**
   - Folder: `~/rex-test` or your real folder
   - Output: `~/rex-data/<project>-output`
   - **Start scan**
3. Watch the **📊 Jobs** page auto-refresh
4. When done → **📥 Review** to triage low-confidence items
5. **🔎 Search** anything

---

## Scan a Folder

### UI
1. **📁 Scan** page → set source + output → **Start scan**
2. Live progress bar + 5 metrics + current filename
3. Open **📊 Jobs** in another tab to see it auto-refresh

### CLI

```bash
# With a wizard (asks for project, output, name)
rex scan ~/path/to/folder

# Direct
rex scan ~/path/to/folder --project accsell --name "products-q4"
```

### What gets created

```
~/rex-data/
├── jobs/job_<sha>/              # job metadata + per-file records + decisions
├── projects/accsell/            # project config
│   └── vectors_*.lance/         # LanceDB vectors (384-dim)
└── accsell-output/              # ORGANIZED COPY of source files
    ├── INDEX.md
    ├── Marketing/{Docs,PDFs,Spreadsheets,Images,...}/
    ├── Sales/{Docs,PDFs,...}/
    ├── _Review/                 # low-confidence items
    └── _Unsorted/               # no domain match
```

**Source files are never modified.** Sort = copy, not move.

---

## Triage with HITL Review

When `confidence < threshold`, files land in `_Review/`. When the LLM picked
a category outside your declared domains, files land in `_Unsorted/`. Both
queue up for you.

### UI
1. **📥 Review** page → point at the output folder
2. See pending counts: `(N low-conf · M no-domain)`
3. For each card:
   - Click a domain button to accept
   - Or type a new domain → **✅ Move to new**
   - Or **🗑️ Trash** (deletes from output; source untouched)
   - Or **⏭️ Skip**
4. Decision saved to `_decisions/{name}.user.json` for the kNN learning loop

### From Claude (MCP)
```
You: "Rex, what's pending review?"
Claude → rex_pending_review(...)  → shows the queue
You: "Mark the first 5 as Sales"
Claude → rex_decide_bulk(...)     → applies all 5
```

---

## Search Your Knowledge Base

### UI
**🔎 Search** page → type a query → see semantic matches.

### CLI
```bash
rex search "Q4 revenue planning"
rex search "campaign ROI" --top-k 20
```

### Programmatic
```python
from rex.ml.provider import ModelProvider
from rex.vectorstore import get_vector_store
from rex.config import get_settings

settings = get_settings()
model = ModelProvider(settings)
store = get_vector_store(settings)

await store.initialize()
embedding = await model.embed("quarterly revenue")
matches = await store.search(embedding, top_k=10)
for m in matches:
    print(m.metadata.get('filename'), m.similarity_score)
```

---

## Use Rex from Claude (MCP)

### Setup
```bash
rex serve --stdio        # for Claude Desktop / Cursor
# or
rex serve --http --port 8765      # for browser-based MCP clients
```

### Register with Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "rex": { "command": "rex", "args": ["serve", "--stdio"] }
  }
}
```

### 12 tools you can call

| Tool | Purpose |
|---|---|
| `rex_pending_review(output_path)` | List HITL queue |
| `rex_review_card(output_path, index)` | One item details |
| `rex_decide(output_path, filename, category)` | Move one item |
| `rex_decide_bulk(output_path, filenames, category)` | Batch move |
| `rex_list_categories(output_path)` | Show taxonomy |
| `rex_business_context()` | Current domains + threshold |
| `search(project, query, top_k=5)` | Semantic search |
| `get_file(project, file_id)` | File metadata |
| `get_decision(project, file_id)` | Classification record |
| `get_catalog(project, doc='overview')` | Catalog markdown |
| `get_duplicates(project, job_id)` | Duplicate report |
| `list_jobs(project)` / `job_status(project, job_id)` | Job state |

---

## Watch a Running Job

### UI
**📊 Jobs** page — auto-refresh every 2s. Stuck warning fires if no
heartbeat for 5 min.

### CLI
```bash
rex tail                  # most-recent in-progress job
rex tail --latest         # same
rex tail job_a1b2c3       # specific job (ID prefix works)
```

Output looks like:
```
🟢 scanning   S= 100 C=   0 O=   0 D=  0 idle 1s   · file_100.pdf
🟢 scanning   S= 150 C=   0 O=   0 D=  0 idle 0s   · file_150.pdf
⚠️ scanning  S= 150 C=   0 O=   0 D=  0 idle 312s · file_150.pdf      ← stuck
🟢 routing    S= 150 C=   1 O=   0 D=  0 idle 1s   · file_001.pdf
Done — final status: awaiting_review
```

---

## Kill / Resume a Scan

**Kill:** Ctrl-C in the terminal, or close the Streamlit tab — Rex writes
per-file as it goes, so disk truth is always recoverable.

**Resume:** Just rerun `rex scan` against the same source folder. Rex
hashes the path to produce a stable `job_id`, then:
- already-scanned files → skip (FileRecord exists)
- already-classified files → skip (FileDecision exists)
- already-sorted files → skip (destination exists with matching size)

Net cost of a kill: ~1 file (the in-flight one).

---

## Backup & Restore

### Tier 2+3 (config + metadata, tiny — back up always)
```bash
tar -czf ~/rex-backup-$(date +%Y%m%d).tar.gz \
  -C ~ \
  AntiGravity_Projects/Proj1/CleanUp/.raven/business_context.json \
  AntiGravity_Projects/Proj1/CleanUp/.raven/manifest.json \
  rex-data/jobs \
  rex-data/projects
```

### Tier 4 (organized output, bulky)
```bash
rsync -av --delete ~/rex-data/<project>-output/ \
  /Volumes/ExternalDrive/rex-output/
```

### Restore
```bash
tar -xzf ~/rex-backup-20260607.tar.gz -C ~
```

---

## Change Settings

### UI
**⚙️ Settings** page — 4 tabs:
| Tab | What you can change |
|---|---|
| 🖥️ System | Read-only — deployment, vector store, paths |
| 🎯 Business | Edit BusinessContext (mirrors Onboarding) |
| 🔐 Secrets | Mask + update API keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`, …) |
| 🧠 Classifier | Pick algorithm for next scan |

API keys write to `.env.local` in the project root; never logged.

---

## Switch Classifier Algorithm

### From code (per scan)
```python
from rex.orchestrator.builder import build_classifier_pipeline

# Fast baseline — uses kNN over labeled HITL history
pipeline = build_classifier_pipeline("knn", k=5)

# Cold start — LLM picks from your domains
pipeline = build_classifier_pipeline(
    "llm_zero_shot", candidates=["Marketing", "Sales", "Strategy"],
)

# Ensemble (best quality once you have data)
from rex.ml.classifier import get_classifier
members = [get_classifier("knn", k=5), get_classifier("llm_zero_shot")]
ensemble = get_classifier("ensemble", members=members, weights=[0.6, 0.4])
pipeline = build_classifier_pipeline(classifier=ensemble)

# Default LLM-per-file path (legacy, slow but no setup)
from rex.orchestrator.builder import build_default_pipeline
pipeline = build_default_pipeline()
```

### From CLI
```bash
# (Coming in next minor release — currently set in code)
```

---

## Common Gotchas

| Symptom | Fix |
|---|---|
| Jobs page shows "No scans yet" but data exists | Rex needs `~/rex-data/jobs/`; check path expansion |
| `_Review/` is huge | Lower threshold OR add more HITL labels (kNN warms up) |
| LLM scan is slow | Switch to `kNN` classifier (use_classifier_pipeline) |
| Ollama "context length exceeded" | Embedding input got too long — Scanner truncates to 1500 chars |
| Search returns nothing | Vector store not initialized; check `~/rex-data/projects/*/vectors_*.lance/` |

For deep-dive on what's happening under the hood, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).
