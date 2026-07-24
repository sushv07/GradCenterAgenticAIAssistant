# Project Handoff — CSULB Graduate Center Agentic AI Assistant

> **Audience:** a senior engineer (human or a fresh Claude Code session) picking up
> this repository with no access to prior conversations. It explains *why* the
> system is shaped the way it is, not just what exists. Read this top-to-bottom
> once; after that you should be able to make a change and defend it.

**Last updated:** end of the Master's Knowledge workstream, Phase 7 (corpus quality).
**Active branch:** `feature/masters-retrieval-evaluation`.

---

## 1. Project Overview

### Purpose
A question-answering assistant for the **CSULB Graduate Center**. A prospective or
current graduate student asks a natural-language question ("What GPA do I need for
the MPA program?", "When is the MBA application deadline?", "Who's the Linguistics
advisor?") and the system returns a grounded, cited answer built from **official
CSULB pages only**. It is a **retrieval-grounded** assistant: knowledge lives in a
vector store built from real university content, never in a model's parameters.

### Users
- **Primary:** prospective and current CSULB graduate applicants using the public
  web app.
- **Secondary:** the maintaining engineer, who runs deterministic evaluations and
  knowledge-base health checks.

### Architecture at a glance
A **deterministic, multi-agent RAG pipeline**, deliberately *not* an
LLM-in-the-loop agent. Routing, retrieval, and answer assembly are rule-based and
reproducible; an LLM is only ever an optional, tightly-scoped synthesis layer that
is **off by default**. The stack is:

- **Frontend:** Streamlit (deployed to Streamlit Community Cloud).
- **Backend:** FastAPI service (deployed to Render via Docker).
- **Retrieval:** local **ChromaDB** persistent vector store, **`all-MiniLM-L6-v2`**
  embeddings (sentence-transformers, 384-dim, CPU), cosine distance. **No OpenAI,
  no external LLM API** anywhere in the primary path.
- **Knowledge acquisition:** a web-scraping + normalization layer that turns
  official CSULB pages into structured records and retrievable documents.

There are **two distinct bodies of work** in this repo, and it is important to keep
them separate in your head:

1. **The production assistant** (originally doctoral-program focused) — the live
   app, built across an earlier set of "productionization" phases (config, DI,
   FastAPI, reliability, observability, deployment). This is on `main`.
2. **The Master's Knowledge workstream** (the focus of the recent work and this
   handoff) — a shared, reusable ingestion pipeline plus a new master's-program
   acquisition layer that flows into the same vector store. This is what the
   active branch contains.

A **third, self-contained artifact** also lives here: a frozen **RAG-vs-Fine-Tuning
research experiment** under `experiments/rag_vs_finetuning/`. It is a completed,
checksum-locked study and must be treated as read-only (see §5 and the ground
rules in §12).

---

## 2. Repository Structure

Top-level folders (the ones that matter):

| Folder | Responsibility | Notes |
|---|---|---|
| `domain/programs/` | Engine-independent domain model: `CanonicalProgram`, enums, facts, validation. | Pure data + rules. Imports nothing infrastructural. The "source of truth" schema for a program. |
| `ingestion/masters/` | **Acquisition** — discover → fetch → extract → normalize CSULB master's pages into `CanonicalProgram` records + immutable content-hashed snapshots. | **Infra-free by contract** (see §4). Guarded by an AST test that forbids importing langchain/chroma/embeddings/rag. |
| `ingestion/pipeline/` | **The shared Knowledge Ingestion Pipeline** — source-agnostic contracts + orchestration: `KnowledgeDocument`, deterministic IDs, metadata schema, validator, ports (Protocols), config, `KnowledgePipeline`, and `loaders/` (per-source adapters). | Also **infra-free**. This is the reusable core every knowledge source flows through. |
| `rag/pipeline_adapters/` | **Infra implementations** of the pipeline ports: `recursive_chunker` (langchain splitter), `hf_embedder` (langchain HF embeddings), `chroma_indexer` (langchain Chroma), and `wiring` (production config binding). | Lives under `rag/` precisely because `ingestion/` may not import infrastructure. |
| `rag/` | Production RAG: web `ingestion.py`, `chunking.py`, `store.py` (build + TTL), `retriever.py` (query), `discovery.py` (generic program crawler), and the master's orchestration modules (`masters_discovery.py`, `masters_extraction.py`, `masters_ingest.py`). | The runtime knowledge path. |
| `evals/` | Deterministic evaluation harnesses (no LLM judge). Retrieval evals (Phase 8A doctoral + Phase 6 master's), ingestion evals, metrics, error classification, golden datasets. | This is where "measure before optimizing" lives. |
| `agents/`, `orchestrator.py`, `routing/`, `retrieval/`, `responses/`, `tools/`, `state/`, `contracts/` | The multi-agent request path: routing a query to guidance/answer/advisor/deadlines/eligibility flows and composing a response envelope. | The live application logic (mostly pre-existing). |
| `api/`, `backend/`, `config/`, `obs/` | FastAPI service layer, backend entrypoint, centralized settings, structured observability. | Production plumbing. |
| `experiments/rag_vs_finetuning/` | **FROZEN** research experiment (Tracks A/B/C, comparative analysis). | Read-only. Do not modify — its results are checksum-guarded. |
| `data/`, `advisors*.json`, `programs.json` | Static JSON knowledge/fallback data + the scraped advisor corpus. | |
| `tests/` | The full test suite (run with `pytest`). | |
| `docs/` | Documentation. `docs/legacy/ARCHITECTURE_V1.md` is a superseded design snapshot; **`ARCHITECTURE_ANALYSIS.md`** (repo root) is the canonical phase-by-phase design log. This file lives here. |

Generated/ignored: `chroma_db/` (the production vector store, rebuilt on demand),
`logs/`, `evals/reports/`, `sessions/`, and the experiment's `artifacts/`.

---

## 3. Current Architecture (the knowledge path)

The write path (build the index) and read path (answer a query) meet at the
vector store. Everything below the "shared pipeline" line is source-agnostic.

```
   ACQUISITION (source-specific)              INDEXING (source-agnostic)
   ───────────────────────────                ──────────────────────────
   web/JSON sources                           KnowledgeDocument
        │                                          │  validate_document
   discovery ──▶ fetch ──▶ extract ──▶ normalize   ▼
        │                                       Chunker (RecursiveCharacter, 500/75)
        ▼                                          │
   CanonicalProgram / page dicts                Embedder (all-MiniLM-L6-v2)
        │                                          │
        └──────── loader ──▶ KnowledgeDocument ─▶ Indexer (Chroma, cosine)
                                                    │
                                              production vector store
                                                    ▲
                                              retriever.retrieve(query, k)
```

### Ingestion pipeline (`ingestion/pipeline/`)
The heart of the refactor. `KnowledgePipeline.run(documents, mode, prune)` takes
**any iterable of `KnowledgeDocument`** and does: `validate → chunk → validate →
index`, returning an `IngestionSummary`. It knows nothing about Chroma, embeddings,
or a specific splitter — those are **ports** (Python `Protocol`s in `ports.py`)
satisfied by adapters in `rag/pipeline_adapters/`. Two modes:
- **`build`** — full (re)create of the collection (production's default, a
  clear-then-rebuild "full replace").
- **`upsert`** (+ optional `prune`) — idempotent incremental indexing keyed by
  deterministic chunk IDs; `prune` deletes stale chunks. Used to add a source
  without wiping the collection.

### KnowledgeDocument
The **source-agnostic intermediate representation** (`documents.py`). Every source
becomes a `KnowledgeDocument(text, source_url, content_type, document_id,
metadata)` before the pipeline touches it. This is the single most important
abstraction: **adding a new knowledge source is writing a new loader that emits
`KnowledgeDocument`s — never a change to chunking, embedding, or indexing.**
Metadata is a flat dict of primitives (ChromaDB cannot store nested metadata).
`metadata.py` defines the production schema (`program_name`, `degree`,
`degree_level`, `department`, `college`, `content_type`, `source_url`,
`document_id`, `canonical_document_id`, `page_title`, `crawl_depth`, …).

### Discovery
Two layers, reused, not duplicated:
- **Directory discovery** (`ingestion/masters/discovery.py`): parses the Graduate
  Studies master's index — a **card-based** layout (~67 program "cards," each an
  anchor whose text ends in a degree in parens like `Accountancy (MS)`, plus
  advisor/deadline sub-tables). Produces a `DiscoveryManifest`.
- **Nested page discovery** (`rag/discovery.py`, orchestrated by
  `rag/masters_discovery.py`): a **generic, program-agnostic** crawler — signal-
  based `classify_page` (8 workflow categories), `score_link_relevance`, bounded
  depth, same-domain filtering, per-program and cross-program URL dedup. It was
  originally built for doctoral programs and is reused unchanged for master's; the
  master's layer only adds cross-program dedup, canonical-URL normalization, and a
  navigation-bleed host guard.

### Extraction
`ingestion/masters/extraction.py` isolates the main content region
(`<main>`/`article`/…), strips nav/header/footer/aside, drops boilerplate
(addresses, carousels, cookie banners), and — as of Phase 7 — strips Drupal
news/teaser widget containers. `extract_main_content_text()` is the public
full-text extractor used to build documents. Fetching is **redirect-aware**
(`fetch_page_final` returns the final URL) so provenance is truthful and redirect
targets deduplicate.

### Chunking
`rag/pipeline_adapters/recursive_chunker.py` wraps langchain's
`RecursiveCharacterTextSplitter` at **chunk_size=500, overlap=75**, with a
separator hierarchy. It reproduces the legacy production chunking **byte-for-byte**
(same chunk IDs `md5(url)[:8]_{index:04d}`, same metadata) so the migration changed
nothing observable. Chunk metadata = document metadata + `chunk_id`/`chunk_index`,
so **all metadata survives chunking**.

### Embeddings
`all-MiniLM-L6-v2` via langchain `HuggingFaceEmbeddings` (CPU, normalized). Wrapped
by `hf_embedder.py`. Chosen for: local/offline, fast on CPU, good semantic quality
on English academic text, small footprint (matters on Render's 512 MB instance).

### Vector store
ChromaDB persistent collection `csulb_grad_center`, cosine distance
(`hnsw:space=cosine` → similarity in [0,1]). Built by `rag/store.build_vector_store`
which **clears the directory then rebuilds** (full replace — this is where
idempotency and stale-pruning come from at the production level). `get_or_build_store`
adds TTL caching (24h), self-healing, and — as of Phase 5 — an optional master's
source append.

### Retriever
`rag/retriever.py`: embed query → Chroma cosine search (over-fetch `k*2`) → filter
by `min_score=0.30` → return top-`k` with metadata. Supports `page_type` /
`program_name` filters. **This is frozen for evaluation purposes** — the retriever
is the thing we measure, not the thing we tune (see §8, §11).

### Evaluation
`evals/run_masters_retrieval_evals.py` + `evals/metrics_retrieval_ranking.py`.
Deterministic, **no LLM judge, no network in tests**. A golden dataset of 25 cases
runs through the *real* production retriever against an isolated evaluation store;
metrics are Recall@1/3/5, MRR, first-relevant-rank, latency. Failures are
**classified with evidence** (store chunk count + a deep k=20 probe distinguishes
acquisition gap vs ranking vs embedding limitation).

---

## 4. Engineering Decisions (the *why*)

**Why ports & adapters (contracts in `ingestion/`, infra in `rag/`)?**
`ingestion/` is protected by an architecture-invariant test
(`tests/test_ingestion_masters_isolation.py`) that forbids importing
langchain/chroma/embeddings/torch/rag anywhere under it. This keeps the acquisition
layer light and testable (bs4 + stdlib + pydantic only). But a chunk→embed→index
pipeline inherently *needs* that infrastructure. The resolution: the **pipeline
contracts and orchestration** live in `ingestion/pipeline/` (pure), and the
**concrete Chroma/embedding/splitter backends** live in `rag/pipeline_adapters/`.
This was a deliberate, discussed decision — the alternative (a top-level
`knowledge_ingestion/` package) was rejected to honor the "evolve the existing
package" instruction, and putting infra in `ingestion/` was rejected because it
would break the invariant.

**Why one shared pipeline instead of two (experiment + production)?**
Chunk/embed/index logic was duplicated between the frozen experiment and `rag/`.
The refactor extracted a single implementation both can reference. Production was
migrated onto it **behavior-preservingly** (byte-identical chunk IDs/metadata,
same Chroma store), proven by the existing store/retriever tests staying green.

**Why is master's added via `upsert`/append rather than a new build command?**
The engineering goal was "master's becomes just another production source." So
master's documents are composed into the *same* `build_vector_store` call (or
upserted into the same collection) — one unified index, one code path, no forked
pipeline. Config-gated (`MASTERS_INGESTION_ENABLED`, default off) and **fail-safe**:
if the master's crawl errors, it returns `[]` and the base build still succeeds.

**Why default the master's feature flag OFF?**
Enabling it adds a multi-minute live crawl to the deployed app's rebuild path
(which runs on TTL/first-request on a constrained Render instance). Defaulting off
keeps deployed behavior and all tests unchanged until an operator explicitly opts
in via one env var — matching the repo's existing `LLM_SYNTHESIS_ENABLED` pattern.
It satisfies "configurable without code changes" without a surprise operational hit.

**Why directory-card documents (Phase 7)?**
Advisor names/emails and per-term deadlines exist *only* in the directory cards,
which were never indexed — so the advisor eval category scored 0%. Rather than a
separate advisor lookup, each card became a small `KnowledgeDocument` flowing
through the *same* pipeline. This is the "integrate into the existing model, not a
separate retrieval path" principle in action.

**Why is the retriever/embeddings/chunking off-limits during quality work?**
The Phase 6 evaluation showed that 4 of 5 failures were **corpus** problems
(missing content, boilerplate, nav bleed), not ranking problems. Evidence said the
cheapest, highest-impact fixes were in acquisition. So Phase 7 improved the corpus
and left retrieval untouched — and Recall@5 rose from 86.96% → 91.30% with **zero**
retrieval changes.

**Why deterministic everything (fixtures, seeds, checksums)?**
Reproducibility is the foundation of the whole project's credibility. Golden
datasets, committed HTML fixtures, deterministic chunk/document IDs, and
content-hashed snapshots mean any result can be regenerated and any regression
caught. The frozen experiment took this to the extreme (SHA-256-guarded corpus,
benchmark, and reports).

---

## 5. Completed Phases

*(Named "workstreams" here to avoid colliding with the experiment's internal
Track A/B/C condition names.)*

### Workstream 1 — The production assistant (pre-existing, on `main`)
Built earlier across many phases (branch names `phase-5a` … `phase-10i`): centralized
config, dependency injection, FastAPI service layer, API contracts, health/readiness
endpoints, graceful degradation, retry strategy, controlled LLM integration (off by
default), retrieval/ingestion **evaluation + observability**, Dockerization, and
Render + Streamlit Cloud deployment. This is the live doctoral-focused assistant.
Treat it as a stable substrate.

### Workstream 2 — The RAG vs Fine-Tuning experiment (FROZEN, `experiments/`)
A complete research study (its own P5–P12): frozen corpus → chunking/embeddings →
Track A (Pure RAG) → frozen benchmark → Track B (LoRA fine-tune via MLX) → Track C
(Hybrid) → comparative analysis → conclusions. **Headline result:** Pure RAG
decisively beat both fine-tuning-only and the hybrid (retrieval grounding dominated
small-data fine-tuning). This experiment is why the production system is
retrieval-grounded, and it is **read-only**.

### Workstream 3 — Knowledge Ingestion + Master's Acquisition (active)
The recent work, in commit order:

1. **Shared knowledge ingestion pipeline** (`9c4144f`) — ports & adapters core.
2. **Migrate RAG build path to shared pipeline** (`8af06f6`) — production adopts it,
   behavior-preserving.
3. **Master's Phase 1 — directory discovery** (`5692cc4`) — validate the card parser
   against the live index (67 programs), committed HTML fixture, baseline report.
4. **Master's Phase 2 — nested page discovery** (`5549f3f`) — reuse the generic
   crawler + cross-program dedup; 5-program pilot.
5. **Master's Phase 3 — extraction → KnowledgeDocument** (`c1193ae`) — reuse the
   calibrated extractor; a new master's loader; validated documents.
6. **Master's Phase 4 — pipeline integration** (`da6daac`) — pilot docs flow through
   the shared pipeline (chunk/embed/index), idempotent upsert.
7. **Master's Phase 5 — production build integration** (`348d708`) — master's becomes
   a config-gated source in `get_or_build_store`, one unified collection.
8. **Master's Phase 6 — retrieval evaluation framework** (`920dff1`) — 25-case golden
   dataset, rank metrics, evidence-based failure classification, baseline report.
9. **Master's Phase 7 — corpus quality** (`86f350f`) — widget stripping,
   redirect-aware canonical URLs, nav-bleed guard, directory-card indexing.
   Raised Recall@5 to 91.30% with no retrieval changes.
10. **Master's Phase 8 — full-catalog expansion** (`9f98c6b`) — scaled acquisition
    from the 5-program pilot to all 67 discoverable programs with **no** pipeline
    change. Added a thin, instrumented orchestration layer
    (`rag/masters_catalog*.py`: build / metrics / report / CLI) that builds an
    isolated full-catalog store and audits it. Live build: 3467 chunks, 67/67
    program coverage. Recall@5 held at 91.30% at 8× corpus size; the only cost was
    rank-1 dilution from same-topic pages across programs. Surfaced three
    corpus-quality anomalies (a PDF indexed as text, a stale `fall-2021` page, the
    CLA redirect class).
11. **Master's Phase 9A — corpus hygiene** (`9f98c6b`) — two deterministic,
    URL-based acquisition filters in the master's layer: unsupported resource
    types (`.pdf/.doc/.docx/.ppt/.pptx`) and term-year archive slugs
    (`…/fall-2021`), plus a non-HTML `Content-Type` guard. Removed 579 noise
    chunks (−16.7%) with **identical** retrieval metrics — the removed content
    never contributed a relevant hit.
12. **Master's Phase 9B — CLA acquisition repair** (this commit) — see below.

### Phase 9B — CLA Acquisition Repair

**Root cause.** The legacy `cla.csulb.edu` departmental CMS was decommissioned;
the Graduate Studies directory still links its dead paths, so 18 programs
(14 unique seeds) 302-redirect to the generic College of Liberal Arts homepage
and had no dedicated content. A live probe confirmed a verified replacement page
exists on the migrated site (`www.csulb.edu/college-of-liberal-arts/<dept>/…`)
for **every** affected program; the 4 other CLA-hosted programs (Asian Studies,
Teaching Chinese, Philosophy, Music) still resolve and were left untouched.

**Architecture.** A generic, data-driven **seed-override** mechanism:
`config/masters/seed_overrides.json` holds 14 verified `stale → replacement`
entries (with reason + verification date), and
`rag.masters_discovery.apply_seed_overrides()` remaps matching seeds
(scheme/slash-insensitive) **before nested discovery and card building**, so
crawl seeds and each directory card's citation both point at the live page.
Unaffected programs pass through as the same object; a missing/invalid config is
a no-op (identical to pre-9B). Added reusable **dead-seed detection**
(`dead_seed_candidates`) that flags the cross-host "redirect magnet" signature in
the build audit, so future directory rot is self-detecting rather than requiring
another manual investigation. `ingestion/`, retriever, chunking, embeddings, and
the evaluation framework are untouched.

**Validation.** Dedicated program coverage **49/67 → 67/67**; master's chunks
**2675 → 3142 (+467 / +17.5%)**; redirect magnets eliminated (dead-seed report:
none); retrieval metrics unchanged; no regressions. Full suite: **1059 passed,
9 documented pre-existing failures**.

**Note on MRE-021.** The Political Science case now retrieves the correct
migrated program page at rank 1 (score 0.81) — a genuine repair of the former
acquisition gap. It still records "fail" only because the golden dataset's
`expected_urls` references the obsolete `cla.csulb.edu` URL. Updating that
benchmark expectation is deliberately deferred to a **separate future change**
(the evaluation set is out of scope for acquisition phases).

---

## 6. Current Branch

**`feature/masters-retrieval-evaluation`** (HEAD = `920dff1`, one commit ahead of
its origin). Its purpose: house the **retrieval evaluation framework and baseline**
(Phase 6), and now the **Phase 7 corpus-quality improvements**, currently
**uncommitted** in the working tree. Modified: `ingestion/masters/extraction.py`,
`rag/masters_discovery.py`, `rag/masters_extraction.py`, `rag/masters_ingest.py`,
`evals/masters_retrieval_eval_cases.json`, `evals/MASTERS_RETRIEVAL_BASELINE.md`,
`tests/test_masters_knowledge_documents.py`; added:
`tests/test_masters_corpus_quality.py`. The next action is to review and commit
Phase 7 (see §12).

The full linear history from `9c4144f` through `920dff1` (+ the uncommitted Phase 7)
is all present on this branch. Earlier branches are labels at phase boundaries along
the same line.

---

## 7. Git Branch History (the important ones)

| Branch | Points at | What it introduced |
|---|---|---|
| `main` | `8810d63` | The deployed doctoral assistant (Streamlit Cloud + Render). The stable base. |
| `feature/masters-canonical-schema` | `08a595d` | The `CanonicalProgram` domain model, the frozen RAG-vs-FT experiment, and a repo cleanup (removed accidental `" 2"` duplicate files, archived legacy `ARCHITECTURE.md`). |
| `refactor/knowledge-ingestion-pipeline` | `da6daac` | The shared pipeline, production migration onto it, and master's Phases 1–4 (discovery → nested → extraction → pipeline integration). |
| `feature/masters-production-build` | `348d708` | Master's Phase 5 — the config-gated production build integration. |
| `feature/masters-retrieval-evaluation` | `920dff1` (+ uncommitted) | Master's Phase 6 evaluation framework and Phase 7 corpus quality. **Active branch.** |

Many `phase-*` branches (5a–10i, 8a–9d) exist from the original assistant build; they
are historical and already merged conceptually into `main`. The tag
`masters-acquisition-v1` marks the end of master's Phase 3.

**Note on branches:** the recent phases were each committed on a differently-named
feature branch, but they form **one linear history**. If you want them consolidated,
they can be fast-forwarded/merged; nothing has been pushed beyond what `origin/*`
already reflects, and the active branch is 1 commit ahead of its remote.

---

## 8. Evaluation Results (current retrieval baseline)

Measured with the production retriever (`k=5`, `min_score=0.30`) over the 25-case
master's golden dataset, against an isolated evaluation store. **Before/after Phase 7:**

| Metric | Phase 6 baseline (v1) | Phase 7 (v2) | Δ |
|---|---|---|---|
| Recall@1 | 82.61% | 82.61% | = |
| Recall@3 | 86.96% | 86.96% | = |
| Recall@5 | 86.96% | **91.30%** | **+4.3 pt** |
| MRR | 0.8406 | **0.8514** | +0.011 |
| Cases passed | 20/25 | **21/25** | +1 |
| Store noise (nav-bleed/utm chunks) | 264 | 0 | −264 (689→431 chunks) |

Perfect-recall categories (100% R@1): gpa, deadlines, tuition, curriculum,
international, faq_shared, multi_hop, admission_requirements, and **doctoral_guard**
(master's ingestion did **not** regress existing doctoral retrieval). Advisor went
0% → 100% after directory-card indexing.

The evaluation store is a **bounded, isolated** rebuild (5 pilot master's programs
depth-1 + the static base sources), not the full 67-program catalog and not the
deployed collection. Metrics are directional, not production-scale.

---

## 9. Known Issues / Limitations

- **Only 5 pilot master's programs are indexed.** The full 67-program catalog has
  not been crawled in production; `MASTERS_INGESTION_ENABLED` is off by default.
  Metrics are pilot-scale.
- **`department` / `college` metadata are always empty** — extraction of these from
  program pages is a documented deferred gap (never fabricated).
- **Out-of-scope queries still return low-scored chunks.** `min_score=0.30` is
  permissive; there is no "answerability" gate. Both negative eval cases fail by
  design (retrieval returns ~0.4–0.67-scored FAQ chunks). Fixing this belongs at the
  answer layer, not retrieval.
- **One genuine ranking miss** (transcripts query, expected page at rank 7) —
  a candidate for reranking, but only one case, so not yet justified.
- **A true acquisition gap** (Political Science): the directory URL 301-redirects to
  the CLA college homepage; **no PoliSci program content exists** in the crawlable
  corpus. This needs a real source page, not retrieval work.
- **Directory cards compete with overview queries.** Adding card documents nudged one
  department-overview query from rank 1 → 4 (behind card chunks). Reported honestly;
  a future `content_type`-aware ranking could address it.
- **9 pre-existing test failures** (`test_experiment_isolation::test_chroma_import_confined…`
  and 8 in `test_prompt_experiments`). These predate all master's work and are
  **unrelated** to it — every phase confirmed "same 9, zero new failures." Do not
  spend time on them unless explicitly asked.
- **Nav-bleed guard is host-based** — some cross-links may still slip; it's a
  heuristic, not a proof.

---

## 10. Roadmap (future phases)

Ranked by evidence-backed expected impact (from the Phase 7 report):

1. **Scale acquisition to all 67 master's programs** and run the full production
   build (enable `MASTERS_INGESTION_ENABLED`, measure rebuild time on Render).
2. **Fix the CLA-template / stale-redirect class of pages** generically — several
   CLA-hosted programs redirect to college homepages with no program content;
   acquire the correct source pages. (Highest corpus-quality impact at scale.)
3. **Metadata/answerability improvements** — populate `department`/`college`;
   add an out-of-scope threshold or answerability gate at the answer layer.
4. **Answer-layer evaluation for master's** — extend beyond retrieval to grounded
   answer quality (the retrieval baseline is the prerequisite, now done).
5. **Reranking / query rewriting** — only after 1–3; current evidence justifies at
   most one case, so it is explicitly *not* the next priority.
6. **Expand the golden dataset** as coverage grows (more programs, more categories,
   variance/seed sweeps).

---

## 11. Engineering Principles (the project's philosophy)

These are not slogans — they were applied and defended at every phase, and you are
expected to hold to them.

- **Prefer reuse over duplication.** The master's track is ~85% reuse: the generic
  crawler, the calibrated extractor, the shared pipeline, the domain model. New code
  is a thin orchestration/loader layer. "One implementation, not two."
- **Audit before coding.** Every phase began by reading the existing code and asking
  "does a mechanism already solve this?" The answer was usually yes.
- **Deterministic pipelines.** Deterministic document/chunk IDs, committed fixtures,
  seeded splits, content-hashed snapshots, no-network tests. Results must be
  reproducible.
- **Measure before optimizing.** The retrieval evaluation (Phase 6) came *before*
  any quality work (Phase 7). Improvements are chosen by metric impact, not intuition.
- **Evidence-driven improvements.** Every failure is classified with concrete
  evidence (store counts, probe ranks, DOM inspection). "Do not guess" is a literal
  rule in the failure classifier.
- **Respect architectural invariants.** `ingestion/` stays infra-free (enforced by an
  AST test). The shared pipeline is extended via **new loaders**, never modified.
  Frozen artifacts stay byte-identical.
- **Additive, minimal, reviewable changes.** Each phase is one focused commit with a
  small surface; production modules are touched only where genuinely required.
- **Fail-safe in production.** New sources never break the base build (master's
  acquisition returns `[]` on error).
- **Honest reporting.** Tradeoffs are reported, not hidden (the directory-card ranking
  regression is in the report). When a test harness had a bug that polluted the local
  store, it was disclosed, verified, and cleaned up rather than papered over.
- **Config over code.** Behavior toggles are env-var feature flags read at point of
  use (matching the existing `LLM_*` pattern), keeping `config/settings.py` pure.

---

## 12. How To Continue (for the next session)

### Environment
- **Run tests and scripts with `/opt/miniconda3/bin/python3`.** That interpreter has
  the full stack (`chromadb`, `langchain`, `sentence-transformers`, `pytest`). The
  bare `python3` on this machine (Xcode/CLT 3.9) does **not** have chromadb and is
  only relevant to the frozen MLX experiment, which you should not touch.
- Network is available (the acquisition layer crawls live CSULB pages). The
  `all-MiniLM-L6-v2` model is cached locally, so embedding is offline.
- Full suite: `cd` to the repo root, then
  `/opt/miniconda3/bin/python3 -m pytest -q`. Expect **~1023 passed, 9 failed** — the
  9 are the pre-existing, unrelated failures listed in §9. **Any other failure is a
  regression you introduced.**
- **Local `chroma_db/` may be empty** (it is gitignored and rebuilt on demand). The
  first retrieval triggers a live rebuild (~30–60 s, network). Useful commands:
  `python -m rag.store --rebuild` (build/verify the store),
  `python -m rag.retriever "your query"` (ad-hoc retrieval),
  `uvicorn api.app:app` (backend), `streamlit run app.py` (frontend) — all with the
  miniconda interpreter. Set `MASTERS_INGESTION_ENABLED=true` to include master's in
  a rebuild (`MASTERS_INGESTION_DEPTH` tunes crawl depth).

### Immediate next step
**Phase 7 is complete but uncommitted** on `feature/masters-retrieval-evaluation`.
Review `git status` / `git diff --stat`, then create the Phase 7 commit (corpus-
quality improvements). The pattern used throughout this project: stage only that
phase's files, show `git diff --cached --stat`, and **wait for the maintainer's
approval before committing** (the maintainer has reviewed and lightly reworded every
commit message — do not auto-commit).

### How to make a change safely
1. **Adding a knowledge source?** Write a loader in `ingestion/pipeline/loaders/`
   that emits `KnowledgeDocument`s. Do **not** modify the pipeline core.
2. **Improving corpus quality?** Work in the acquisition layer
   (`ingestion/masters/`, `rag/masters_*`). Keep `ingestion/masters/` infra-free
   (the isolation test will fail otherwise). Do **not** touch retriever/embeddings/
   chunk size unless evidence specifically points there.
3. **Changing production build behavior?** It's `rag/store.get_or_build_store` (build
   orchestration) — additive, config-gated. The shared pipeline stays untouched.
4. **Anything in `experiments/rag_vs_finetuning/`** — don't. It's frozen and
   checksum-guarded; the isolation test `test_experiment_isolation` and the freeze
   verifier will catch modifications.

### How to evaluate a change
The eval store recipe is committed code only (the original build scripts were
session-scratch and are gone — this is the procedure):
1. **Base sources:** `rag.ingestion.ingest_pages(use_discovery=False)` →
   `rag.chunking.chunk_documents(pages)`.
2. **Master's pilot:** `rag.masters_ingest.masters_build_documents(enabled=True,
   index_html=<small directory HTML listing the 5 pilot seeds>)` — pilot seeds are
   listed in `evals/masters_retrieval_eval_cases.json`'s `_store` note and the
   pilot reports.
3. **Index both** into a scratch dir via
   `rag.pipeline_adapters.chroma_indexer.ChromaVectorIndex(...)
   .build_from_langchain_documents(base + masters)`.
4. **Run:** `evals.run_masters_retrieval_evals.run_evals(load_cases(),
   store=<langchain Chroma over that dir>)`; compare Recall@1/3/5 + MRR to
   `evals/MASTERS_RETRIEVAL_BASELINE.md`.

Never point an eval build at the real `chroma_db/` — always a scratch directory.
Tests for the eval framework itself are fully offline
(`tests/test_masters_retrieval_evals.py`).

### Ground rules recap
- Reuse first. Extend via loaders. Keep `ingestion/` infra-free.
- Measure before optimizing; classify failures with evidence.
- One focused, additive commit per phase; wait for maintainer approval to commit.
- Never modify the frozen experiment or the shared pipeline core.
- Report tradeoffs honestly.

### Canonical references in the repo
- **`ARCHITECTURE_ANALYSIS.md`** (root) — the detailed, phase-by-phase design log and
  the RAG-vs-FT experiment retrospective. The deepest single source of design
  rationale.
- **`evals/MASTERS_RETRIEVAL_BASELINE.md`** — the live retrieval baseline + Phase 7
  before/after + ranked recommendations.
- **`experiments/rag_vs_finetuning/reports/`** — the frozen experiment's conclusions,
  lessons learned, and future work.
- Per-phase pilot reports live next to their code (`rag/MASTERS_*_PILOT.md`,
  `ingestion/masters/MASTERS_DISCOVERY_REPORT.md`).
