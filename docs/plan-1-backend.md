# Rex Plan: Part 1 — Backend

## Scope

Everything that runs without a UI: agents, ML layer, database, extraction, MCP server.

---

## B1. Project Foundation

- [ ] `pyproject.toml` with all dependencies
- [ ] `docker-compose.yml` (rex-app, postgres+pgvector, ollama)
- [ ] `.env.local` template
- [ ] Pydantic models: `FileRecord`, `FileContext`, `FileDecision`, `JobStatus`
- [ ] Config module: loads env vars, validates, exposes typed settings
- [ ] Logging setup (structured JSON logs)

## B2. Database Layer

- [ ] PostgreSQL schema via Alembic migrations
- [ ] Tables: `files`, `embeddings`, `decisions`, `jobs`, `categories`, `tags`
- [ ] pgvector extension enabled, HNSW index on embeddings
- [ ] `entity_type` + `relation_hint` columns on files and decisions (Phase II graph readiness)
- [ ] SQLAlchemy async models
- [ ] Repository pattern: `FileRepo`, `JobRepo`, `CatalogRepo`

## B3. Scanner Agent

- [ ] Async directory walker (os.walk via asyncio — yields one file at a time)
- [ ] File fingerprinting: SHA-256 hash, MIME detection, size, timestamps
- [ ] Text extraction via Unstructured.io:
  - PDF (layout-aware, tables, embedded images)
  - DOCX, PPTX, TXT, MD, HTML, CSV, Excel
- [ ] Image handling (Phase 1):
  - EXIF metadata extraction (Pillow)
  - Send to Gemini Flash for description/OCR
- [ ] Video handling (Phase 1): fingerprint + park (metadata only, no deep analysis)
- [ ] Embedding generation: extracted text -> Ollama all-minilm -> 384d vector
- [ ] Write `FileRecord` + embedding to PostgreSQL
- [ ] Stream `FileContext` to next stage
- [ ] Progress reporting: files scanned / total estimate / current file

## B4. LLM Router Agent

- [ ] PydanticAI agent definition with `FileDecision` output model
- [ ] Model provider abstraction: Ollama (local) / Bedrock (cloud) via env config
- [ ] Structured prompt template:
  - Input: file metadata + extracted text (first 2000 chars) + image descriptions + top-3 similar files from pgvector
  - Output: category, tags[], relevance (1-5), duplicate_of, action (keep/archive/trash), reasoning
- [ ] Similarity search: query pgvector for top-3 neighbors (cosine distance)
- [ ] Dedup logic:
  - SHA-256 exact match -> mark as exact duplicate
  - Cosine > 0.92 -> mark as near-duplicate (auto-dedup, keep best)
  - Cosine 0.80-0.92 -> mark as "related" (flag for user review)
- [ ] Catalog context: feed existing categories to the router so it reuses/extends, not reinvents
- [ ] Write `FileDecision` to PostgreSQL
- [ ] Temperature=0, deterministic classification
- [ ] Batch/parallel: process multiple files concurrently (Ollama parallel mode)

## B5. Organizer Agent

- [ ] Read `FileDecision` from PostgreSQL
- [ ] Create organized output folder structure:
  - Category-based subfolders (from router decisions)
  - `_catalog/` with index.md, tags.md, categories.md
  - `_metadata/` with per-file JSON sidecars
- [ ] File operations: copy (not move by default — user confirms move later)
- [ ] Metadata sidecar per file: original path, hash, category, tags, relevance, decision reasoning
- [ ] Index generation: Obsidian-compatible markdown with wiki-links
- [ ] Handle conflicts: same filename in different source paths
- [ ] Pre-organized input detection: flag `pre_organized: true`, offer enhance-in-place mode

## B6. Prefect Orchestration

- [ ] `scan_flow`: Scanner agent as a Prefect flow with tasks
- [ ] `route_flow`: LLM Router as a Prefect flow (parallel tasks per file batch)
- [ ] `organize_flow`: Organizer as a Prefect flow
- [ ] `rex_pipeline`: master flow that chains scan -> route -> organize
- [ ] Retry policies: transient failures (Ollama timeout) auto-retry 3x
- [ ] State management: job can be paused/resumed
- [ ] Observability: Prefect dashboard for monitoring runs

## B7. MCP Server

- [ ] FastMCP server with tools:
  - `scan(folder_path)` -> start a scan job, return job_id
  - `status(job_id)` -> job progress
  - `search(query, filters)` -> semantic search over organized files
  - `get_file(file_id)` -> file metadata + content path
  - `get_catalog(job_id)` -> full catalog index
  - `get_categories()` -> list of discovered categories
  - `get_duplicates(job_id)` -> duplicate groups for review
- [ ] Works with Claude Desktop, ChatGPT, any MCP client

## B8. Plugin Architecture

- [ ] `StoragePlugin` base class (abstract):
  - `walk(path)` -> async generator of file entries
  - `read(path)` -> file bytes
  - `write(path, bytes)` -> write file
  - `exists(path)` -> bool
- [ ] `LocalFSPlugin` — Phase 1 implementation
- [ ] `S3Plugin` — Phase 2 stub (interface only)
- [ ] `GoogleDrivePlugin` — Phase 2 stub
- [ ] Plugin registry: discovered via entry points or config

---

## Dependency List

```
# Core
pydantic>=2.0
pydantic-ai
sqlalchemy[asyncio]
asyncpg
alembic
prefect>=3.0

# Extraction
unstructured[all-docs]
python-magic

# ML
ollama
google-genai          # Gemini Flash
pillow                # EXIF

# Vector
pgvector

# MCP
fastmcp

# Utils
python-dotenv
structlog
rich                  # CLI progress
httpx
```
