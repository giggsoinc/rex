# Rex Pipeline — Guru Walk-Through

You point Rex at a folder. From that moment to a clean organized output, every file takes a journey through 3 agents and 4 storage layers. Here is exactly what happens.

---

## Master Flow

| Stage | What Happens | File / Module | Class / Function |
|-------|-------------|---------------|------------------|
| **0** | CLI parses `rex scan <folder>` | `src/rex/cli/main.py` | `main()` |
| **0a** | Dispatches to scan command | `src/rex/cli/scan.py` | `main()` → `_run()` |
| **0b** | Loads `.env` + `.env.local` + resolves Gemini key | `src/rex/config.py` | `get_settings()` |
| **0c** | Builds wired pipeline (agents + stores) | `src/rex/orchestrator/builder.py` | `build_default_pipeline()` |
| **0d** | Initializes LanceDB vector store | `src/rex/vectorstore/lancedb_store.py` | `LanceDBStore.initialize()` |
| **0e** | Creates or resumes job (idempotent by folder hash) | `src/rex/orchestrator/state.py` | `JobStore.create_or_resume_job()` |
| **1** | Orchestrator runs the 3-stage pipeline | `src/rex/orchestrator/pipeline.py` | `RexPipeline.run()` |

---

## Stage 1: Scanner Agent (per file, streaming)

**Module:** `src/rex/agents/scanner.py` · **Class:** `LocalScanner`

For each file walked from the folder:

| Step | Action | File / Module | Function |
|------|--------|--------------|----------|
| 1.1 | Walk directory (async) | `src/rex/plugins/local_fs.py` | `LocalFSPlugin.walk()` |
| | • Skips `.git`, `.venv`, `node_modules`, hidden | | |
| | • Returns one `FileEntry` at a time (never buffers full dir) | | |
| 1.2 | Compute SHA-256 hash (off-thread 64KB chunks) | `src/rex/agents/scanner.py` | `sha256_of_file()` |
| 1.3 | Idempotency check: hash already in job? | `src/rex/orchestrator/state.py` | `JobStore.get_file_by_hash()` |
| | • If yes → skip extraction + embed, reuse existing record | | |
| 1.4 | Detect MIME type from extension | `src/rex/agents/scanner.py` | `detect_mime()` |
| 1.5 | Detect media type (TEXT/IMAGE/VIDEO/AUDIO/ARCHIVE/BINARY) | `src/rex/agents/scanner.py` | `detect_media_type()` |
| 1.6 | Extract text content | `src/rex/agents/scanner.py` | `extract_text()` |
| | • `.txt/.md/.json/.csv` → direct read | | |
| | • `.pdf/.docx/.pptx/.xlsx` → Unstructured.io | `unstructured.partition.auto` | `partition()` |
| | • Fallback: regex-grep printable ASCII strings | | |
| | • Truncate to `REX_MAX_TEXT_CHARS` (default 2000) | | |
| 1.7 | (Images only) Vision description | `src/rex/ml/vision.py` | `VisionEngine.describe_image()` |
| | • Calls Gemini Flash if key set | `google.genai` | `Client.generate_content()` |
| | • Skipped with warning if no key | | |
| 1.8 | (Images only) EXIF metadata | `src/rex/agents/scanner.py` | `LocalScanner._read_exif()` |
| | • Pillow extracts EXIF dict | `PIL.Image` | `_getexif()` |
| 1.9 | Build `FileRecord` Pydantic model | `src/rex/models/schemas.py` | `FileRecord` |
| 1.10 | Persist FileRecord to JSON | `src/rex/orchestrator/state.py` | `JobStore.save_file()` |
| 1.11 | Generate embedding via Ollama | `src/rex/ml/provider.py` | `ModelProvider.embed()` |
| | • Calls `all-minilm` model (384d vector) | `ollama` | `AsyncClient.embed()` |
| 1.12 | Upsert vector + metadata to LanceDB | `src/rex/vectorstore/lancedb_store.py` | `LanceDBStore.upsert()` |
| | • Cosine-distance index for similarity search | | |
| 1.13 | Find top-3 neighbors (for Router context) | `src/rex/vectorstore/lancedb_store.py` | `LanceDBStore.search()` |
| 1.14 | Collect existing categories from this job | `src/rex/orchestrator/state.py` | `JobStore.list_decisions()` |
| 1.15 | Yield `FileContext` to orchestrator | `src/rex/models/schemas.py` | `FileContext` |

**Stage 1 output:** A stream of `FileContext` objects — each carries the file record, embedding, neighbors, and known categories.

---

## Stage 2: LLM Router Agent (per file, intelligence)

**Module:** `src/rex/agents/router.py` · **Class:** `LLMRouter`

For each FileContext from Stage 1:

| Step | Action | File / Module | Function |
|------|--------|--------------|----------|
| 2.1 | Idempotency: decision already exists? | `src/rex/orchestrator/state.py` | `JobStore.get_decision()` |
| | • If yes → skip LLM call, reuse decision | | |
| 2.2 | **Deterministic dedup check first** | `src/rex/agents/router.py` | `LLMRouter._check_dedup()` |
| | • Look at top neighbor's cosine similarity | | |
| | • ≥ 0.9999 → `EXACT_DUPLICATE` → action = TRASH | | |
| | • ≥ 0.92 → `NEAR_DUPLICATE` → action = ARCHIVE | | |
| | • ≥ 0.80 → `RELATED` → flag only | | |
| 2.3 | Build structured prompt for LLM | `src/rex/agents/router.py` | `build_user_prompt()` |
| | • Filename + extension + media_type + size + modified | | |
| | • Extracted text (first 1500 chars) | | |
| | • Image description (if any) | | |
| | • Top-3 similar neighbors with similarity scores | | |
| | • Existing categories list | | |
| 2.4 | **LLM call with 3-retry backoff** | `src/rex/agents/router.py` | `LLMRouter._classify_with_retry()` |
| | • Calls `ModelProvider.generate()` with JSON mode | `src/rex/ml/provider.py` | `ModelProvider._ollama_generate()` |
| | • Routes to Ollama / Bedrock / Gemini based on `REX_LLM_PROVIDER` | | |
| | • Local default: qwen3:8b via Ollama | `ollama` | `AsyncClient.chat()` |
| 2.5 | Parse model output | `src/rex/agents/router.py` | `extract_json()` |
| | • Strips markdown fences, regex-finds JSON object | | |
| 2.6 | Validate against `FileDecision` schema | `src/rex/models/schemas.py` | `FileDecision` |
| | • category, tags[], relevance 1-5, action, reasoning | | |
| | • Pydantic raises on invalid → retry | | |
| 2.7 | Normalize fields (sanitize category, lowercase tags) | `src/rex/agents/router.py` | `LLMRouter._build_decision()` |
| 2.8 | Overlay dedup result on LLM decision | `src/rex/agents/router.py` | `LLMRouter.route()` |
| | • Dedup wins: TRASH for exact, ARCHIVE for near-dup | | |
| 2.9 | Fallback if all retries fail | `src/rex/agents/router.py` | `LLMRouter._fallback_decision()` |
| | • Heuristic category from extension | | |
| | • Mark `unclassified` tag, relevance=3 | | |
| 2.10 | Persist `FileDecision` to JSON | `src/rex/orchestrator/state.py` | `JobStore.save_decision()` |
| 2.11 | Brief sleep (50ms) to keep Ollama happy | `src/rex/orchestrator/pipeline.py` | `asyncio.sleep(0.05)` |

**Stage 2 output:** A `FileDecision` per file persisted on disk.

---

## Stage 3: Organizer Agent (per file, physical placement)

**Module:** `src/rex/agents/organizer.py` · **Class:** `LocalOrganizer`

For each (FileRecord, FileDecision) pair:

| Step | Action | File / Module | Function |
|------|--------|--------------|----------|
| 3.1 | Pick destination folder | `src/rex/agents/organizer.py` | `LocalOrganizer.organize()` |
| | • action=TRASH → `_Trash/<category>/` | | |
| | • action=ARCHIVE → `_Archive/<category>/` | | |
| | • action=KEEP + relevance≤2 → `_Flagged/<category>/` | | |
| | • action=KEEP + relevance≥3 → `<category>/` | | |
| 3.2 | Sanitize category to safe path | `src/rex/agents/organizer.py` | `safe_path_segment()` |
| | • Strip spaces, special chars; keep slashes for nesting | | |
| 3.3 | Conflict resolution (same name, different hash) | `src/rex/agents/organizer.py` | `LocalOrganizer.organize()` |
| | • Suffix filename with first 8 chars of SHA-256 | | |
| 3.4 | Copy file (never move) | `src/rex/plugins/local_fs.py` | `LocalFSPlugin.copy()` |
| | • Uses `shutil.copy2` in thread pool to preserve metadata | | |
| 3.5 | Write metadata sidecar | `src/rex/agents/organizer.py` | `LocalOrganizer.organize()` |
| | • `_metadata/<hash[:16]>.json` per file | | |
| | • Full FileRecord + FileDecision + organized_at timestamp | | |

After ALL files placed, `finalize()` builds the catalog:

| Step | Action | File / Module | Function |
|------|--------|--------------|----------|
| 3.6 | Generate `_catalog/overview.md` | `src/rex/agents/organizer.py` | `_write_overview_md()` |
| 3.7 | Generate `_catalog/index.md` (master table) | `src/rex/agents/organizer.py` | `_write_index_md()` |
| 3.8 | Generate `_catalog/categories.md` (tree by category) | `src/rex/agents/organizer.py` | `_write_categories_md()` |
| 3.9 | Generate `_catalog/tags.md` (tag cloud) | `src/rex/agents/organizer.py` | `_write_tags_md()` |
| 3.10 | Generate `_catalog/duplicates.md` (review list) | `src/rex/agents/organizer.py` | `_write_duplicates_md()` |

**Stage 3 output:** Organized folder + sidecars + 5 catalog markdown files.

---

## What Could Run in Parallel (Today vs Future)

**Today (sequential per file):**
- Files are scanned one at a time (limited by LocalFSPlugin)
- Routing is sequential (one LLM call at a time)
- Organizing is sequential (one copy at a time)

**Already plumbed for parallelism, just needs flipping on:**

| Parallel Job | Where | Trigger |
|--------------|-------|---------|
| Concurrent Ollama LLM calls | `src/rex/ml/provider.py` `embed_batch()` | Already supports `REX_OLLAMA_PARALLEL=N` |
| Concurrent embeddings | `src/rex/ml/provider.py` `embed_batch()` | Same env var |
| Concurrent scanning + extraction | Future: needs `asyncio.gather()` in `RexPipeline.run()` | Easy refactor |
| Concurrent vision calls | `src/rex/ml/vision.py` | One Gemini call per image — naturally batch-able |

**Future: Prefect-based parallelism (already in plan-3-integration.md):**
- Each file is a Prefect task → all 500 files fan out across N workers
- Retry policies per file
- Resume from any failed task
- Observability dashboard

---

## Quick Reference: The 7 Storage Locations

| Where | What Lives Here |
|-------|----------------|
| `~/rex-data/jobs/<job_id>/job.json` | Top-level job state |
| `~/rex-data/jobs/<job_id>/files/*.json` | One FileRecord per file scanned |
| `~/rex-data/jobs/<job_id>/decisions/*.json` | One FileDecision per file classified |
| `~/rex-data/vectors.lance/` | LanceDB Parquet — embeddings + metadata |
| `~/rex-data/output/<category>/*` | Organized copies of your files |
| `~/rex-data/output/_metadata/*.json` | Per-file sidecars (full provenance) |
| `~/rex-data/output/_catalog/*.md` | 5 Obsidian-compatible browse files |

---

## The One-Line Mental Model

> **Walk → Hash → Extract → Embed → Find Neighbors → Ask LLM → Validate → Dedup → Place → Catalog.**

Every file. Every time. Resumable. Idempotent. Source folder untouched.
