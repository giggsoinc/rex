# Rex — Data Cleanup & Knowledge Intelligence

> **A local-first, AI-powered system that turns a messy folder of mixed files
> into a clean knowledge base — categorized, searchable, and exposed to your
> tools via MCP.**

Rex scans a folder, understands what each file is, sorts it into a clean
domain → type taxonomy, and gives you both a Streamlit UI and an MCP API to
query it. Everything runs locally by default (Ollama + LanceDB); cloud LLMs
are opt-in per folder.

---

## What Rex Does (in 60 seconds)

```
   /Users/you/Products/           Rex                    /Users/you/rex-data/
   ├── 1,800 mixed files     ─────────────▶              ├── Marketing/
   ├── 17 GB                   1. fingerprint            │   ├── Docs/    (240)
   ├── PDFs · DOCs · PPTs      2. embed (LanceDB)        │   ├── PDFs/    (350)
   ├── XLSX · CSV · MD         3. classify (ML or LLM)   │   └── Spreadsheets/ (35)
   ├── PNG · JPG · MP4         4. sort + index           ├── Sales/
   └── ...                     5. HITL gate              ├── Strategy/
                                                          ├── Brand/
                                                          ├── _Review/   (low confidence)
                                                          ├── _Unsorted/ (no domain match)
                                                          └── INDEX.md
```

---

## Key Features

| | |
|---|---|
| 🧠 **Plug-and-play classifier** | kNN · LLM zero-shot · ensemble · drop in BERTopic / SetFit later |
| 🎯 **Business-context aligned** | You declare domains once; Rex snaps files to them |
| 🟡 **HITL by design** | Low-confidence items wait in `_Review/` until you triage |
| 🔄 **Learning loop** | Your corrections train the next scan via append-only kNN |
| 🗂️ **12-bucket type taxonomy** | Docs · Notes · PDFs · Spreadsheets · Presentations · Images · Videos · Audio · Archives · Code · Data · Other |
| 📥 **Resumable scans** | Kill anytime; rerun resumes from disk truth |
| 📡 **MCP-native** | 12 tools so Claude / Cursor / browsers can query Rex |
| 💚 **Local by default** | Ollama + all-minilm + LanceDB. Cloud LLMs opt-in per folder |
| 🚦 **LiteLLM task router** | Per-task model + fallback chain. Cheap stages local, quality stages cloud. Cost logged per call. |
| 🔐 **Editable Settings** | Masked secrets, model profile picker, per-domain config |
| 🟢 **Live job tracking** | Heartbeat-backed Jobs page + `rex tail` CLI |

---

## Quick Start

### System dependencies (install once)

Rex needs a few native binaries that pip can't install. On macOS:

```bash
brew install ollama                  # local LLM backend (required for default profile)
brew install --cask libreoffice      # legacy .doc/.xls/.ppt extraction (optional, recommended)
brew install tesseract               # offline OCR fallback (optional)
brew install ffmpeg                  # video metadata (optional)
```

On Linux:
```bash
curl -fsSL https://ollama.com/install.sh | sh    # ollama
sudo apt install libreoffice tesseract-ocr ffmpeg
```

Run `rex doctor` at any time to see what's installed vs missing.

### Install + first scan

```bash
# 1. Clone & install
git clone https://github.com/giggsoinc/rex.git
cd rex
pip install -e .

# 2. Health check (do this first!)
rex doctor

# 3. Initialize (picks deployment + vector store)
rex init

# 3. UI
streamlit run src/rex/ui/app.py
# → http://localhost:8501

# 4. or CLI
rex scan ~/path/to/folder --project demo
rex tail        # live-stream progress
rex search "quarterly revenue"

# 5. MCP server (for Claude / Cursor)
rex serve --stdio    # or --http --port 8765
```

---

## Architecture (one diagram)

```
┌──────────────────────────────────────────────────────────────────┐
│  SOURCE FOLDER  (never modified)                                 │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼
   ┌──── Scanner ────┐   sha256 · mime · extract text · embed (384d)
   │                 │
   ▼                 ▼
LanceDB         FileRecord    ◀── job_id = sha256(source_path)[:16]
            │
            ▼
   ┌── ClassifierRouter ──┐   kNN · LLM zero-shot · ensemble
   │                      │
   └────► FileDecision    │   category + confidence + tags + action
            │
            ▼
   ┌── SortEngine ──┐     Aligns to BusinessContext domains
   │                │     Maps extension → 12-bucket type taxonomy
   └────► destination       Low-conf → _Review/  ·  no match → _Unsorted/
            │
            ▼
   ┌── INDEX.md ──┐         Obsidian-friendly root catalog
            │
            ▼
   🟡 AWAITING_REVIEW       HITL inbox in Streamlit + MCP
            │
            ▼
   ┌── learning loop ──┐    decisions feed kNN index
            │
            ▼
       ✅ SERVE           Search · Browse · MCP · GraphRAG (Phase 2)
```

Full Mermaid diagram: [`docs/diagrams/classification-pipeline.html`](docs/diagrams/classification-pipeline.html)

---

## LiteLLM Task Router (per-task model selection)

Rex names every LLM call a "task" and routes each task through LiteLLM with a
primary model + fallback chain:

| Task | Default primary | Fallback | Per call |
|---|---|---|---|
| embed | Ollama `all-minilm` (local) | — | $0 |
| classify | Ollama `qwen3:8b` (local) | Gemini Flash-Lite | $0 → $0.0001 |
| vision_describe | Gemini Flash-Lite | GPT-4o-mini | $0.0003 |
| entity_extraction (Phase 2) | Gemini Flash | Claude Haiku | $0.001 |
| reason | Claude Sonnet | GPT-4o | $0.02 |

Routing lives in `.raven/llm_routing.yaml`. `BusinessContext.model_profile`
selects a bundled profile (`local`, `balanced`, `premium`, `custom`).
Every call is appended to `.raven/usage.jsonl` with `task`, `model`,
`input_tokens`, `output_tokens`, `cost_usd`, `fallback_used`.

See [`docs/architecture.md#litellm-task-router`](docs/architecture.md#litellm-task-router)
for the full diagram, config schema, and provider matrix.

## Storage Model

```
~/rex-data/                          Rex home
├── jobs/job_<sha>/                  per-scan state (files + decisions)
├── projects/<name>/                 per-project vector store
│   └── vectors_<name>_<ts>.lance/   isolated LanceDB
└── <project>-output/                organized copy with INDEX.md
                                     + _Review/ + _Unsorted/

<project>/.raven/                    project config
├── manifest.json                    project manifest
└── business_context.json            domains + threshold + profile

.env.local                           API keys (masked in UI)
```

---

## Read Next

| Doc | What you'll get |
|---|---|
| [HOW_TO_USE.md](HOW_TO_USE.md) | Task-oriented walkthroughs for every workflow |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | Pipeline, algorithms, HITL, drift — the conceptual model |
| [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) | Module layout · extending classifiers · contributing |
| [docs/diagrams/classification-pipeline.html](docs/diagrams/classification-pipeline.html) | Interactive pipeline diagram |

---

## Status

- **Phase 1** — sort, taxonomy, HITL, learning loop · ✅ shipping
- **Phase 2** — GraphRAG entity extraction, soft ontology · 🔜 next
- **Phase 3** — formal ontology, multi-modal (CLIP / CLAP) · later

## License

Internal — Giggso. See LICENSE.
