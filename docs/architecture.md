# Rex Architecture

## System Overview

Rex is a multi-agent data cleanup and knowledge management system.
Point at a folder. Get intelligent classification, dedup, and organization.

## Architecture Diagram

```mermaid
graph TB
    subgraph UI["Phase 1: Streamlit UI"]
        ST[Streamlit App<br/>Point folder / Progress / Browse / Search]
    end

    subgraph MCP_LAYER["MCP Server"]
        MCP[Rex MCP Tools<br/>scan / search / get_file / get_catalog / status]
    end

    subgraph ORCHESTRATOR["Prefect Orchestrator"]
        PF[Prefect Flows<br/>Retry / Parallel / Observe / Pause-Resume]
    end

    subgraph PIPELINE["Agent Pipeline"]
        direction LR
        SCAN[Scanner Agent<br/>Walk dir / Extract text<br/>Fingerprint / Stream]
        ROUTER[LLM Router Agent<br/>Classify / Tag / Dedup<br/>Route / Decide]
        ORG[Organizer Agent<br/>Move files / Write meta<br/>Build index / Catalog]
        SCAN -->|file_context| ROUTER
        ROUTER -->|FileDecision| ORG
    end

    subgraph ML_LAYER["ML Layer"]
        direction TB
        OLLAMA[Ollama<br/>dolphin-mistral: classify+route<br/>all-minilm: embeddings]
        GEMINI[Gemini Flash<br/>Vision / OCR / Image understanding<br/>PDF embedded images]
        PROVIDER[Model Provider<br/>env-configured<br/>local=ollama / cloud=bedrock]
        PROVIDER --> OLLAMA
        PROVIDER --> GEMINI
    end

    subgraph EXTRACT["Extraction Layer"]
        UNS[Unstructured.io<br/>PDF / DOCX / PPTX / HTML<br/>Images / Excel / Email]
    end

    subgraph STORAGE["Storage Layer"]
        PG[(PostgreSQL + pgvector<br/>files / embeddings<br/>decisions / catalog)]
        FS[File System<br/>Organized Output<br/>Metadata Sidecars]
        S3[S3 / Drive<br/>Cloud sync<br/>Phase 1: local only]
    end

    subgraph PHASE2["Phase II"]
        FALKOR[(FalkorDB<br/>Knowledge Graph<br/>Entities + Ontology)]
    end

    ST --> MCP
    MCP --> PF
    PF --> PIPELINE
    ROUTER --> ML_LAYER
    SCAN --> EXTRACT
    ROUTER --> PG
    ORG --> FS
    ORG --> PG
    FS -.->|future| S3
    PG -.->|feeds| FALKOR

    classDef agent fill:#2d5aa0,stroke:#1a3a6b,color:#fff
    classDef ml fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef storage fill:#059669,stroke:#047857,color:#fff
    classDef ui fill:#d97706,stroke:#b45309,color:#fff
    classDef future fill:#6b7280,stroke:#4b5563,color:#fff

    class SCAN,ROUTER,ORG agent
    class OLLAMA,GEMINI,PROVIDER ml
    class PG,FS,S3 storage
    class ST ui
    class FALKOR future
```

## LLM Router Detail

```mermaid
graph LR
    subgraph INPUT["File Context"]
        META[filename / size / type<br/>modified / hash]
        TEXT[extracted text<br/>first 2000 chars]
        VIS[image description<br/>from Gemini Flash]
        EMB[embedding vector<br/>768d from all-minilm]
        SIM[similar files<br/>top 3 by cosine]
    end

    subgraph ROUTER["LLM Router (PydanticAI)"]
        PROMPT[Structured prompt<br/>+ existing catalog context]
        LLM[dolphin-mistral<br/>JSON mode / temp=0]
        VALID[Pydantic validation<br/>FileDecision model]
        PROMPT --> LLM --> VALID
    end

    subgraph OUTPUT["FileDecision"]
        CAT[category]
        TAGS[tags array]
        REL[relevance 1-5]
        DUP[duplicate_of: id or null]
        ACT[action: keep / archive / trash]
        RSN[reasoning: one sentence]
    end

    INPUT --> ROUTER
    ROUTER --> OUTPUT
```

## LiteLLM Task Router

Rex routes each pipeline stage to a different model via **LiteLLM**, a unified
OpenAI-compatible client that supports 100+ providers (Ollama, Gemini, Claude,
GPT, Bedrock, Groq, …). The router lets cheap stages run locally and expensive
stages escalate to cloud — per scan, per task.

### Why a router

| Without router | With router |
|---|---|
| One global `llm_provider` for everything | Per-task model + fallback chain |
| Embedding goes through the LLM provider too | Embed = local, generate = cloud (independent) |
| No cost visibility per scan | Cost logged per call to `.raven/usage.jsonl` |
| Provider errors blow up the scan | Built-in fallback chain — retries before fail |
| One global `BusinessContext.model_profile` is decorative | model_profile selects a routing YAML profile |

### Architecture

```mermaid
graph LR
    subgraph TASKS["Pipeline stages — each names a 'task'"]
        EMB["embed()"]
        CLS["classify()"]
        VIS["vision_describe()"]
        EXT["extract_entities()<br/>(Phase 2)"]
        REA["reason()"]
    end
    subgraph ROUTER["rex/ml/routing.py — LiteLLM adapter"]
        YAML[".raven/llm_routing.yaml<br/>profiles + per-task chains"]
        ROUTE["routing.get_model(task=)"]
        FB["fallback chain<br/>primary → 2nd → ..."]
        BUDGET["max_cost_per_call_usd<br/>guardrail"]
        YAML --> ROUTE
        ROUTE --> FB
        ROUTE --> BUDGET
    end
    subgraph PROVIDERS["Providers (via LiteLLM)"]
        OLL[Ollama local<br/>qwen3:8b · all-minilm]
        GEM[Gemini Flash / Flash-Lite]
        CLD[Claude Haiku / Sonnet]
        GPT[OpenAI GPT-4o / mini]
        BED[AWS Bedrock]
        GRQ[Groq]
    end
    subgraph LOG["Observability"]
        USE[".raven/usage.jsonl<br/>per-call tokens + cost + model + task"]
    end
    TASKS --> ROUTER
    ROUTER --> PROVIDERS
    PROVIDERS --> USE
```

### Routing config (`.raven/llm_routing.yaml`)

```yaml
tasks:
  embed:
    primary: ollama/all-minilm:latest      # free, local
    fallback: []
  classify:
    primary: ollama/qwen3:8b               # local first
    fallback: [gemini/gemini-2.0-flash-lite]
    max_cost_per_call_usd: 0.001
  vision_describe:
    primary: gemini/gemini-2.0-flash-lite
    fallback: [openai/gpt-4o-mini]
  entity_extraction:                       # Phase 2 GraphRAG
    primary: gemini/gemini-2.0-flash
    fallback: [anthropic/claude-haiku-4-5]
  reason:
    primary: anthropic/claude-sonnet-4-5
    fallback: [openai/gpt-4o]
    max_cost_per_call_usd: 0.10

profiles:
  local:    {all_tasks: ollama}                   # privacy-first, free
  balanced: {embed_classify: ollama, vision_extract: gemini}  # default
  premium:  {classify: gemini→claude, vision_extract: claude}
  custom:   user_override                         # full YAML control
```

The active profile comes from `BusinessContext.model_profile` (set in
🚀 Onboard) — no code change to swap.

### Provider × Task Matrix (`balanced` profile)

| Task | Primary | Fallback | Per-call cost |
|---|---|---|---|
| `embed` | Ollama all-minilm | — | $0 |
| `classify` | Ollama qwen3:8b | Gemini Flash-Lite | $0 → $0.0001 |
| `vision_describe` | Gemini Flash-Lite | GPT-4o-mini | $0.0003 |
| `entity_extraction` | Gemini Flash | Claude Haiku | $0.001 |
| `reason` | Claude Sonnet | GPT-4o | $0.02 |

### Cost log

Every call appends one JSON line to `.raven/usage.jsonl`:
```json
{"ts":"2026-06-09T22:14:33Z","task":"classify","model":"ollama/qwen3:8b",
 "input_tokens":480,"output_tokens":64,"cost_usd":0.0,"fallback_used":false}
```

The Raven dashboard at `~/RavenVault/dashboard.html` reads this file (when
wired) to show per-scan, per-model, per-task spend.

## Deployment Topology

```mermaid
graph TB
    subgraph LOCAL["Local (MacBook)"]
        direction TB
        DC[docker-compose.yml]
        L_APP[rex-app container<br/>Python + Streamlit]
        L_PG[postgres + pgvector]
        L_OL[ollama<br/>dolphin-mistral + all-minilm]
        DC --> L_APP
        DC --> L_PG
        DC --> L_OL
    end

    subgraph CLOUD["AWS (Fargate/ECS)"]
        direction TB
        ECS[ECS Task Definition]
        C_APP[rex-app<br/>Fargate]
        C_PG[RDS PostgreSQL<br/>+ pgvector]
        C_ML[Ollama on GPU<br/>OR Bedrock]
        ECS --> C_APP
        ECS --> C_PG
        ECS --> C_ML
    end

    ENV[".env file swap<br/>ONLY thing that changes:<br/>DB URL / LLM endpoint / Storage path"]

    LOCAL ---|same Docker image| ENV
    ENV ---|same Docker image| CLOUD
```

## Data Flow

```
User points at folder
       |
       v
[Scanner Agent]
  - os.walk() async generator (never loads full dir)
  - For each file:
    - SHA-256 hash
    - MIME type detection
    - Unstructured.io text extraction
    - Gemini Flash for images/embedded visuals
    - all-minilm embedding (768d)
    - Write file record to PostgreSQL
    - Yield file_context downstream
       |
       v
[LLM Router Agent]
  - Receives file_context + catalog state
  - Finds top-3 similar files via pgvector cosine
  - Sends structured prompt to dolphin-mistral
  - Gets FileDecision (Pydantic validated)
  - Dedup: hash exact match OR cosine > 0.92 = duplicate
  - Cosine 0.80-0.92 = "related" (flagged, user decides)
  - Writes decision to PostgreSQL
       |
       v
[Organizer Agent]
  - Reads FileDecision
  - Moves/copies file to organized output structure
  - Writes metadata sidecar (.json per file)
  - Updates index.md, tags.md, categories.md
  - Builds Obsidian-compatible catalog
```

## Output Structure

```
~/Rex-Output/{job-name}/
  _catalog/
    index.md            # master file index
    tags.md             # all tags -> files
    categories.md       # category tree
  _metadata/
    {file-hash}.json    # per-file metadata sidecar
    schema.json         # metadata schema
  Documents/
  Presentations/
  Images/
  Code/
  Archives/             # old but valuable
  Flagged/              # needs human review (near-dupes, ambiguous)
  Trash/                # duplicates/junk (review before delete)
```

## Tech Stack Summary

| Layer | Technology | Why |
|-------|-----------|-----|
| Orchestration | Prefect | Retry, parallel, observability, local + cloud |
| Agent logic | PydanticAI | Type-safe structured outputs, model-agnostic |
| Extraction | Unstructured.io | Widest format support (PDF, DOCX, PPTX, HTML, images) |
| Text embeddings | Ollama / all-minilm | Already installed, 45MB, fast, local |
| Classification | Ollama / dolphin-mistral | 7B model, JSON mode, local inference |
| Vision/OCR | Gemini Flash API | Best-in-class image understanding |
| Vector store | pgvector (HNSW) | Same DB as metadata, JOIN-able |
| Database | PostgreSQL | Metadata, decisions, catalog, embeddings |
| UI (Phase 1) | Streamlit | Fast to ship, good enough |
| UI (Phase 2) | NiceGUI | Production-grade |
| MCP | FastMCP | Expose Rex to Claude/ChatGPT/any client |
| Phase II | FalkorDB | Knowledge graph + ontology |

## Environment Parity

```
# .env.local
REX_LLM_PROVIDER=ollama
REX_LLM_ENDPOINT=http://localhost:11434
REX_LLM_MODEL=dolphin-mistral:latest
REX_EMBED_MODEL=all-minilm:latest
REX_VISION_PROVIDER=gemini
REX_DB_URL=postgresql://rex:rex@localhost:5432/rex
REX_STORAGE_BACKEND=local
REX_STORAGE_PATH=./output

# .env.cloud
REX_LLM_PROVIDER=bedrock
REX_LLM_MODEL=claude-haiku-4-5-20251001
REX_EMBED_MODEL=amazon.titan-embed-text-v2
REX_VISION_PROVIDER=gemini
REX_DB_URL=postgresql://rex:xxx@rex-db.rds.amazonaws.com:5432/rex
REX_STORAGE_BACKEND=s3
REX_STORAGE_PATH=s3://rex-output/
```
