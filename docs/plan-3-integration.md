# Rex Plan: Part 3 — Integration, DevOps & Phase II

## Scope

Wiring backend + frontend together, Docker setup, testing, deployment, and Phase II prep.

---

## I1. Docker Compose (Local Dev)

- [ ] `docker-compose.yml`:
  ```yaml
  services:
    rex-app:     # Python app + Streamlit
    postgres:    # PostgreSQL 17 + pgvector
    ollama:      # Ollama with pre-pulled models
  ```
- [ ] Ollama container pre-pulls `dolphin-mistral` + `all-minilm` on first start
- [ ] PostgreSQL init script: create DB, enable pgvector extension
- [ ] Health checks: Ollama ready, PG ready, then rex-app starts
- [ ] Volumes: output folder mapped, PG data persisted
- [ ] Single command start: `docker compose up`

## I2. Configuration Management

- [ ] `.env.local` — local development defaults
- [ ] `.env.cloud` — AWS deployment template
- [ ] `src/rex/config.py` — Pydantic Settings model
  - Validates all env vars on startup
  - Typed access: `settings.llm_provider`, `settings.db_url`
  - Profiles: `REX_PROFILE=full` (dolphin-mistral) or `REX_PROFILE=light` (gemma3:4b)
- [ ] Model warmup on startup: pre-load Ollama models to avoid cold-start latency

## I3. Testing Strategy

- [ ] Unit tests:
  - Pydantic models serialization/validation
  - Config loading from env vars
  - File fingerprinting (known hashes)
  - Dedup threshold logic
- [ ] Integration tests:
  - Scanner: scan a test folder with known files, verify FileRecords in PG
  - Router: classify known file types, verify FileDecisions
  - Organizer: verify output folder structure
  - pgvector: embed and retrieve, verify cosine similarity
- [ ] Test fixtures: small test folder with 10 known files (mix of types)
- [ ] CI: GitHub Actions — lint, type-check, tests against PG+pgvector container

## I4. Database Migrations

- [ ] Alembic setup with async driver (asyncpg)
- [ ] Initial migration: all tables + pgvector extension
- [ ] Migration naming: sequential, descriptive
- [ ] Rollback tested for each migration
- [ ] Schema includes Phase II columns from day one:
  - `entity_type` (varchar) — what kind of knowledge node this becomes
  - `relation_hint` (jsonb) — discovered relationships for graph edges

## I5. Observability

- [ ] Structured logging via `structlog` (JSON in production, pretty in dev)
- [ ] Prefect dashboard: flow runs, task states, failure traces
- [ ] Metrics to track:
  - Files processed per minute
  - LLM router latency per call
  - Embedding generation throughput
  - Dedup hit rate
  - Category distribution
- [ ] Health endpoint: `/health` returns DB, Ollama, storage status

## I6. AWS Deployment (Lift & Shift)

- [ ] Dockerfile: multi-stage build, slim Python image
- [ ] ECS Task Definition generated from docker-compose (via `ecs-cli` or manual)
- [ ] RDS PostgreSQL with pgvector extension
- [ ] Ollama options:
  - Option A: Ollama on GPU EC2 instance (g5.xlarge) as sidecar
  - Option B: Replace with Bedrock Claude Haiku (zero infra for ML)
- [ ] S3 for organized output storage
- [ ] Secrets Manager for API keys (Gemini, etc.)
- [ ] ALB in front of Streamlit for HTTPS
- [ ] Environment: swap `.env.local` -> `.env.cloud`, same image

## I7. Phase II Prep (FalkorDB Knowledge Graph)

- [ ] Schema design: every file becomes a node, every relationship an edge
- [ ] Node types: `File`, `Topic`, `Person`, `Project`, `Date`, `Category`, `Tag`
- [ ] Edge types: `contains`, `duplicates`, `related_to`, `tagged_with`, `authored_by`, `part_of`
- [ ] `entity_type` and `relation_hint` in PG schema feed directly into graph creation
- [ ] Ontology seed: initial schema of node/edge types defined in config
- [ ] Migration script: read PG decisions -> create FalkorDB nodes + edges
- [ ] Query patterns: "Show me everything related to Q3 revenue" traverses graph

---

## Build Order (Implementation Sequence)

```
Day 1: Foundation
  - pyproject.toml + dependencies
  - docker-compose.yml (PG + Ollama)
  - Config module + .env.local
  - Pydantic models (FileRecord, FileContext, FileDecision)
  - DB schema + Alembic initial migration
  - Verify: docker compose up, PG connects, Ollama responds

Day 2: Scanner Agent
  - Async directory walker
  - File fingerprinting (hash, MIME, size)
  - Text extraction via Unstructured
  - Embedding generation via Ollama all-minilm
  - Write to PostgreSQL
  - Verify: scan test folder, check PG records

Day 3: LLM Router Agent
  - PydanticAI agent with FileDecision output
  - Prompt template with catalog context
  - pgvector similarity search (top-3 neighbors)
  - Dedup logic (hash + cosine thresholds)
  - Verify: classify test files, check decisions in PG

Day 4: Organizer Agent + Prefect
  - Organizer: move files, write sidecars, build index
  - Prefect flows: scan_flow -> route_flow -> organize_flow
  - Master pipeline flow
  - Verify: end-to-end scan -> classify -> organize on test folder

Day 5: Streamlit UI
  - Scan page: point at folder, start job
  - Progress page: live updates
  - Browse page: explore organized output
  - Search page: semantic search
  - Verify: full flow via UI

Day 6: Image + Vision
  - Gemini Flash integration for image understanding
  - EXIF extraction
  - Image embedding + classification
  - Review page for near-duplicates
  - Verify: scan folder with images, proper classification

Day 7: MCP + Polish
  - FastMCP server with all tools
  - Settings page
  - Error handling + edge cases
  - Documentation
  - Verify: MCP works with Claude Desktop
```

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Ollama too slow on CPU (16GB Mac) | Scanning takes hours | Light profile with gemma3:4b, parallel mode |
| Unstructured.io fails on corrupt files | Scanner crashes | Try/except per file, log + skip, flag as unprocessable |
| LLM hallucinated categories | Inconsistent classification | Feed existing categories in prompt, validate output |
| pgvector perf at >1M embeddings | Search slows down | HNSW index, partition by job_id |
| Gemini API rate limits | Image processing blocks | Batch + backoff, cache descriptions |
| Docker memory pressure | OOM on 16GB laptop | Light profile, limit Ollama memory, PG shared_buffers tuned |
