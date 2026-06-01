# Rex Plan: Part 2 — Frontend (Streamlit Phase 1)

## Scope

Streamlit UI for Phase 1. Minimal, functional, ships fast.
NiceGUI upgrade is Phase 2.

---

## F1. App Layout

- [ ] Single Streamlit app with sidebar navigation
- [ ] Pages:
  1. **Scan** — point at folder, start scan
  2. **Progress** — live progress of current/past jobs
  3. **Browse** — explore organized output by category
  4. **Search** — semantic search across all indexed files
  5. **Review** — approve/reject flagged items (near-dupes, ambiguous)
  6. **Settings** — model config, output path, thresholds

## F2. Scan Page

- [ ] Folder path input (text input + file browser if available)
- [ ] "Scan" button -> calls backend `scan_flow`
- [ ] Job name auto-generated (folder name + timestamp) or user-provided
- [ ] Options:
  - Output path (default: `~/Rex-Output/{job-name}/`)
  - Mode: full re-org vs. enhance-in-place
  - Include subfolders: yes/no
  - File type filter (optional)
- [ ] Validation: folder exists, readable, estimated file count shown

## F3. Progress Page

- [ ] Real-time progress bar: files scanned / classified / organized
- [ ] Current file being processed
- [ ] Stats: categories discovered, duplicates found, files by action (keep/archive/trash)
- [ ] Job history: past scans with status, date, file counts
- [ ] Cancel/pause button for running jobs

## F4. Browse Page

- [ ] Category tree (expandable sidebar)
- [ ] File list per category with: name, tags, relevance score, action taken
- [ ] Click file -> detail view:
  - Original path vs. new path
  - Extracted text preview
  - Tags, category, relevance
  - Router reasoning
  - Similar files list
- [ ] Filters: by tag, by relevance, by date, by file type

## F5. Search Page

- [ ] Semantic search bar
- [ ] Results ranked by relevance (pgvector cosine similarity)
- [ ] Each result shows: file name, category, tags, relevance score, text snippet
- [ ] Click result -> opens in Browse detail view
- [ ] Filters: category, date range, file type, minimum relevance

## F6. Review Page

- [ ] Near-duplicate groups: show side-by-side comparison
  - File A vs File B: name, size, modified date, text diff preview
  - User picks: keep A, keep B, keep both, merge
- [ ] Ambiguous files (relevance < 3 or no clear category)
  - Show router reasoning
  - User overrides: assign category, change action
- [ ] Bulk actions: approve all suggestions, trash all duplicates

## F7. Settings Page

- [ ] LLM provider: Ollama / Bedrock / OpenAI (dropdown)
- [ ] Model selection (text list from Ollama or configured)
- [ ] Dedup thresholds: exact (hash), near (cosine slider), related (cosine slider)
- [ ] Output format: Obsidian-compatible / flat / custom
- [ ] Gemini API key input (stored in .env, never displayed)

---

## Frontend-Backend Interface

The Streamlit app talks to the backend via **direct Python imports** (same process, Phase 1).
No REST API needed yet. When we go cloud, the MCP server becomes the interface.

```python
# Streamlit calls backend directly
from rex.agents.orchestrator import run_pipeline
from rex.db.repos import FileRepo, JobRepo, CatalogRepo
from rex.ml.embeddings import semantic_search
```

---

## UI Wireframe (ASCII)

```
+---------------------------------------------------+
|  REX  [Scan] [Progress] [Browse] [Search] [Review]|
+--------+------------------------------------------+
|        |                                          |
| Cats   |  Documents (42 files)                    |
| ----   |  +----+----------+------+-----+-------+  |
| > Docs |  | #  | Name     | Tags | Rel | Action|  |
| > Pres |  +----+----------+------+-----+-------+  |
| > Imgs |  | 1  | Q3 Rev.. | q3,  | 5   | keep  |  |
| > Code |  | 2  | Notes..  | mtg  | 4   | keep  |  |
| > Arch |  | 3  | Copy..   | q3   | 2   | trash |  |
|        |  +----+----------+------+-----+-------+  |
|        |                                          |
| Tags   |  [< Prev]  Page 1 of 3  [Next >]        |
| ----   |                                          |
| #q3    |                                          |
| #mtg   |                                          |
| #rev   |                                          |
+--------+------------------------------------------+
```
