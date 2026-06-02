# Rex — Session Handoff

_Last updated: 2026-06-01_

## What Rex is
A **local-first, cloud-parity data cleanup & knowledge-management system**. Point it at a messy folder; it scans → classifies → dedupes → organizes every file into a searchable, Obsidian-compatible catalog. **Source files are copied, never moved.** Exposed via CLI, Streamlit UI, and an MCP server (11 tools for Claude/Perplexity/Manus).

- **Repo:** https://github.com/giggsoinc/rex (public)
- **Local path:** `/Users/giggso/AntiGravity_Projects/Proj1/CleanUp`
- **Stack:** Python 3.11, Ollama (qwen3:8b + all-minilm), LanceDB, Gemini Flash (vision), Pydantic, Rich, FastMCP, Streamlit. Raven guards active.

## Git state (as of handoff)
- **Current branch:** `refactor/style-line-limits` (working tree clean)
- **Commits:**
  - `afa2332` refactor: split 18 files under Raven 150-line limit; print()→logging
  - `00e38ed` fix: load .env regardless of CWD + stop tracking .env.local
  - `c01fab8` feat: Rex pipeline (Phase 1 + scale architecture)
  - `7d936cb` chore: init raven manifest
- **Open PRs (stacked):**
  - **#2** `refactor/style-line-limits → feat/rex-pipeline` (the refactor)
  - **#1** `feat/rex-pipeline → main` (the whole feature)
- **Merge order:** merge #2 into `feat/rex-pipeline`, then #1 into `main`. Or land together.
- **Scale:** 114 source files, ~8,300 lines. Every file ≤150 lines (Raven style limit — pre-commit guard CLEARS clean now).

## Architecture — the 5-agent flow
`rex scan <folder>` runs: **Intent dialog → PreFlight → Planner → Coordinator → Workers → Janitor**

| Stage | Module | Role |
|-------|--------|------|
| Intent | `preflight/intent*.py` | Asks purpose/goal/model every run; estimates tokens+cost+time; recommends Ollama model |
| PreFlight | `preflight/checks*.py` | Parallel env checks (Ollama, embed model, Gemini, disk, deps); hard-fail vs soft-warn |
| Planner | `planner/` | Fast non-LLM walk; segments files into balanced batches by type/size; skip list |
| Coordinator | `coordinator/` | `asyncio` + `mp` (multiprocess) local backends; SQS/Prefect/K8s = stubs |
| Worker | `agents/worker.py` | Batch-scoped Scanner→Router→Organizer; writes to per-worker LanceDB shard |
| Janitor | `janitor/` | Cleanup on complete/kill/crash/periodic; merges shards, compacts, finalizes catalog |

Core agents: `agents/scanner.py` (walk/hash/extract/embed), `agents/router.py` (LLM classify + dedup), `agents/organizer.py` (copy + catalog).

Abstractions (swappable local↔enterprise): `vectorstore/` (LanceDB default + pgvector/Oracle/Chroma stubs), `secrets/` (8 backends), `ml/provider.py` (Ollama/Bedrock/OpenAI), `projects/` (per-project isolation — own vector DB tagged with name+UTC timestamp).

## How to run
```bash
cd /Users/giggso/AntiGravity_Projects/Proj1/CleanUp
pip install -e .                    # one-time; registers `rex` command (Anaconda dep warnings are harmless)
# or: export PYTHONPATH=src and use `python3 -m rex.cli.main ...`

rex project create demo --context "..."          # create isolated project
rex scan tests/fixtures/sample-data --project demo --workers 3 --soft -y   # fixtures smoke test (~1.5 min)
rex scan ~/SomeFolder                            # wizard fires (intent → preflight → plan → confirm)
rex serve                                        # MCP server: stdio + HTTP :8765
streamlit run src/rex/ui/app.py                  # UI at :8501
```
Output lands under `~/rex-data/projects/<name>/output/` — start at `_catalog/overview.md`.

## Verified working
- End-to-end on 14-file fixtures in both `asyncio` and `mp` modes: 3/3 batches, 14 files, 13 vectors merged from 3 shards.
- All 11 MCP tools register. Full public import surface resolves. `.env` loads regardless of CWD.

## Known issues / tech debt
1. **Unstructured.io broken in dev Anaconda env** (`coverage.types.Tracer` error) → PDFs fall back to crude string extraction → can cause false near-duplicate grouping on small PDFs. Fix: clean venv + `pip install -U unstructured`, or add `pdfplumber` as primary PDF extractor.
2. **185 soft Raven warnings** (missing docstrings on small inner helpers like `_do_upsert`; CVE-script-not-installed noise). Non-blocking. Optional follow-up sweep before merge.
3. **`python-magic`/libmagic not installed** — harmless; extension-based MIME fallback. `brew install libmagic && pip install python-magic` to silence.
4. **Disk was at ~98%** earlier on the main volume — watch space on large real-folder runs.
5. **Speed:** qwen3:8b ≈ 30s/file sequential. Use `--workers N --mode mp` for parallelism, or set `REX_OLLAMA_PARALLEL`. Cloud coordinators (SQS/Prefect/K8s) are stubbed — `coordinator/factory.py` interface ready, impls pending.

## Secrets — important
- `.env` and `.env.local` are **gitignored** (untracked). Real Gemini key lives in `.env.local` locally as `REX_GEMINI_API_KEY=...`. Git history only ever held an empty placeholder — no leak.
- Config loader (`config_env.py`) finds env files via: `$REX_ENV_FILE` → CWD → repo root → `~/.rex/`.

## Likely next steps (not started)
- Merge PRs #2 then #1.
- Fix Unstructured.io / add pdfplumber for real PDF extraction.
- Implement a cloud Coordinator backend (SQS+Fargate or Prefect) — interface already exists.
- Optional: clear the 185 soft docstring warnings.
- Phase II (per original vision): FalkorDB knowledge graph, cross-folder semantic linking.

## Conventions
- **Raven guards active.** Pre-commit enforces: 150-line file max (hard), no print() in source (use structlog), no secrets, no inline SQL. Brownfield bugs → `andie-jr`. Planning → `andie`.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Don't commit/push unless asked. Branch off `main`/feature, never commit straight to default.
- Style split pattern used in refactor: keep public module as entry point; move cohesive groups to sibling modules; compose classes via mixins or helper delegation; preserve exact public import API.
