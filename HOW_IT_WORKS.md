# How Rex Works — Conceptual Model

The pipeline, the algorithms, the storage, the HITL loop. No code — just the
mental model.

---

## The One-Sentence Summary

> Rex turns a folder of mixed files into a knowledge base by **fingerprinting**
> every file, **embedding** them into a vector space, **classifying** them
> against your declared business domains, **sorting** them into a clean
> taxonomy, and **gating** uncertain decisions behind a Human-in-the-Loop
> review queue.

---

## The Pipeline (5 stages)

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   SCAN +    │───▶│  CLASSIFY   │───▶│    SORT     │───▶│   INDEX     │───▶│   HITL      │
│   EMBED     │    │             │    │             │    │             │    │   REVIEW    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
   sha256              kNN /              align to            INDEX.md          _Review/
   mime                LLM zero-shot      domains             at root           _Unsorted/
   extract text        ensemble           map ext →           per domain        bulk +
   embed 384-dim                          12 buckets          counts            cards
                                          copy file
                                          (never move)
```

### 1. Scan + Embed

For every file Rex walks:

| Step | Output | Notes |
|---|---|---|
| sha256 | file fingerprint | Idempotency key + drift detection |
| mime + extension | media type | Drives extractor + bucket |
| extract text | first 1500 chars | pdfplumber · python-docx · openpyxl · python-pptx |
| vision describe | (if image) | Gemini Flash or local LLaVA |
| embed | 384-dim vector | `all-minilm` via Ollama by default |

Each FileRecord lands at `~/rex-data/jobs/<job_id>/files/<uuid>.json` and
the embedding into LanceDB at `~/rex-data/projects/<name>/vectors_*.lance/`.

### 2. Classify

A `RouterAgent` produces a `FileDecision`:
```python
{
  "category": "Marketing",
  "confidence": 0.87,
  "action": "keep",
  "tags": ["marketing", "campaign", "src-knn"],
  "reasoning": "knn: classified"
}
```

Two router paths today:

| Router | Speed | When to use |
|---|---|---|
| `LLMRouter` (default, legacy) | ~1 sec/file | Cold start, no labels |
| `ClassifierRouter` (new) | ~5 ms/file | After HITL labels exist OR ensemble setup |

`ClassifierRouter` delegates to the plug-and-play classifier module. See
[the classifier section below](#the-classifier-module).

### 3. Sort

The **SortEngine** is pure logic with no ML — it just routes:

```
if confidence < threshold        → _Review/<filename>
elif category not in domains     → _Unsorted/<bucket>/<filename>
elif action == TRASH             → _Trash/<bucket>/<filename>
elif action == ARCHIVE           → _Archive/<domain>/<bucket>/<filename>
else                             → <domain>/<bucket>/<filename>
```

**Domain alignment:** the LLM may return `"Marketing/Q3"` — SortEngine snaps
that to the closest declared domain (`Marketing`).

**Type taxonomy (12 buckets):**

| Bucket | Extensions |
|---|---|
| Docs | `.doc .docx .rtf .odt .pages` |
| Notes | `.md .txt .rst .org .markdown` |
| PDFs | `.pdf` |
| Spreadsheets | `.xls .xlsx .csv .tsv .ods .numbers` |
| Presentations | `.ppt .pptx .odp .key` |
| Images | `.jpg .png .gif .webp .heic .svg .tiff` |
| Videos | `.mp4 .mov .avi .mkv .webm` |
| Audio | `.mp3 .wav .flac .m4a .ogg` |
| Archives | `.zip .tar .gz .7z .rar` |
| Code | `.py .js .ts .go .java .cpp .rb .rs` |
| Data | `.json .xml .yaml .parquet .sql .db` |
| Other | everything else |

### 4. Index

After all files placed, an `INDEX.md` lands at the output root:

```markdown
# Knowledge Index — Accsell — AI-powered sales platform

Generated: 2026-06-07T18:42Z
Total files placed: 1,800 · Avg confidence: 0.81
Status: AWAITING REVIEW — clear 85 review + 25 unsorted before serving.

## Domains
### Marketing (412 files)
- Docs (40): see [`Marketing/Docs/`](./Marketing/Docs/)
- PDFs (350): see [`Marketing/PDFs/`](./Marketing/PDFs/)
...

## ⚠️ _Review — Needs You (Low Confidence)
- [[Q3_Notes.pdf]] · guessed `Marketing` (conf 0.61) — could be Sales
```

Obsidian-friendly: open the output folder as a vault for wiki-link navigation.

### 5. HITL Review

Status moves to `AWAITING_REVIEW`. The user clears `_Review/` and
`_Unsorted/` via:
- **Streamlit** `📥 Review` page — bulk + card view
- **MCP** `rex_pending_review` + `rex_decide` tools

Each decision is written to `_decisions/<name>.user.json` — the **learning
loop signal**.

---

## The Classifier Module

`src/rex/ml/classifier/` is a self-contained, plug-and-play package. Every
algorithm implements the same `Classifier` Protocol:

```python
class Classifier(Protocol):
    name: str
    def fit(self, examples: list[tuple[list[float], str]]) -> None: ...
    def predict(self, embedding: list[float], **kwargs) -> Prediction: ...
    def explain(self, embedding: list[float]) -> dict: ...
```

`Prediction` is uniform across algorithms:

```python
Prediction(
    category=str,
    confidence=float,                # 0-1
    source=str,                      # "knn" | "llm_zero_shot" | "ensemble"
    candidates=list[(label, score)], # ranked alternatives
    meta=dict,                       # algorithm-specific debug info
)
```

### Algorithms registered today

| Algorithm | How it works | Confidence comes from |
|---|---|---|
| **kNN** | Cosine vote of k nearest neighbors in the labeled index | `winner_count / k` (e.g. 4/5 = 0.8) |
| **LLM zero-shot** | LLM picks from candidate labels with self-reported score | LLM's own confidence field |
| **Ensemble** | Weighted vote across N members | `winner_score / sum_of_scores` |

### How confidence drives routing

```
LLM router      → confidence parsed from JSON          → 0.5 if absent
kNN classifier  → consensus (winner_votes / k)         → 0.0 if empty index
Ensemble        → weighted aggregate score             → entropy = disagreement
```

If `confidence < BusinessContext.confidence_threshold` (default 0.7), file
goes to `_Review/`.

### How the learning loop works

```
1. User triages an item in Review → apply_decision(item, "Marketing", note)
2. Decision saved to _decisions/<name>.user.json (append-only)
3. Next scan: bootstrap_from_decisions() reads them all
4. kNN.fit(examples) loads them into the in-memory index
5. Next file's predict() votes against this labeled set
6. Confidence sharpens as labels accumulate
```

No retraining needed for kNN — appends are O(1) and votes are O(N).

---

## The HITL Contract

Every uncertain decision is gated behind a human. Three trigger types:

| Trigger | What it means | Where it lands |
|---|---|---|
| Low confidence | `score < threshold` | `_Review/` |
| Domain miss | LLM picked outside your declared domains | `_Unsorted/` |
| Policy gate | Destructive op (e.g. mass trash) | Explicit confirm |

HITL is **async** — the pipeline keeps running; queue accumulates.

HITL is **dual-surface** — Streamlit Review page OR MCP tools from Claude.
Decisions sync instantly across both.

---

## Storage Model

```
~/rex-data/
├── jobs/
│   └── job_<sha>/                       per-scan state
│       ├── job.json                     status · counts · heartbeat
│       ├── files/<uuid>.json            FileRecord per file
│       └── decisions/<id>.json          FileDecision per file
│
├── projects/<name>/                     per-project, isolated
│   ├── project.json
│   └── vectors_<name>_<ts>.lance/       LanceDB
│
└── <project>-output/                    organized COPY (never source)
    ├── INDEX.md
    ├── <Domain>/<Bucket>/<file>
    ├── _Review/<file>
    ├── _Unsorted/<bucket>/<file>
    └── _decisions/<name>.user.json      HITL labels (learning loop)
```

**Key invariant:** source files are **never** modified. Rex is copy-only.

---

## Drift Detection

`src/rex/ml/classifier/lifecycle/drift_detector.py` exposes `scan_drift()`
that compares a prior `{path: sha256}` snapshot against current disk:

| Drift type | Detection | Response |
|---|---|---|
| Content drift | `sha256` changed | Re-embed + reclassify |
| Missing | path gone | Orphan vector cleanup |
| New | path appeared | Embed + classify |

Today: scan_drift() is a library function. Wire it into a scheduler or `rex
status` invocation for cron-style monitoring.

---

## Resumability

Rex is designed to be killed and restarted without data loss:

- **Job ID is deterministic** — `sha256(source_path)[:16]` → same folder = same job
- **Per-file persistence** — each `FileRecord` and `FileDecision` is one JSON file
- **Heartbeat** — `job.last_progress_at` updates on every file
- **Idempotent skip** — scan / route / sort each check before doing work

Kill at any time. Rerun. Pipeline picks up at the last consistent point.

---

## What's NOT Yet ML (honest callouts)

| Feature | State |
|---|---|
| **Relevance score** (`1-5`) | LLM emits it; not yet used by SortEngine routing |
| **Entity extraction** | Not built (Phase 2 — GraphRAG) |
| **Cross-corpus dedup** | Within-scan only today; across-scan needs vector backend integration |
| **Active learning** (suggest highest-value items for HITL) | Designed but not implemented |
| **BERTopic / SetFit classifiers** | Drop-in slots open in registry; not built yet |
| **Drift detector scheduler** | Library exists; not wired to cron |
| **Auto-retrain** | Designed; bootstrap_from_decisions() exists but no scheduler |

---

## Phase 2 — What's Coming

```
Phase 1 (today)   Phase 2 (next)             Phase 3 (later)
─────────────     ──────────────             ───────────────
Sort taxonomy     + entity extraction         + formal ontology (OWL/RDF)
HITL Review       + relationship graph        + multi-modal (CLIP / CLAP)
kNN ensemble      + community detection       + active learning
LanceDB vectors   + theme summaries           + agentic loop
                  + Browse → Graph tab
                  + rex_themes(category)
                  + rex_related(doc_id)
```

Phase 2 = **soft ontology** (LLM-extracted, no rigid schema).
Phase 3 = **formal ontology** (engineered types, only if value justifies).

For the developer-facing view, see [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md).
