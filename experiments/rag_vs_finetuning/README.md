# RAG vs. Fine-Tuning Experiment

Isolated experiment area. It reads frozen canonical program records **read-only**
and produces retrieval-neutral projection artifacts. It imports **no** production
RAG, routing, orchestration, LangChain, Chroma, embeddings, or model-serving code,
and production code never imports this package.

## Phase P5 scope (this commit)

1. **Materialize** the approved 12-program reviewed corpus into an immutable
   experiment corpus.
2. **Freeze manifest** with per-record and per-source checksums + an aggregate.
3. **Projection** layer: `CanonicalProgram → list[RetrievalDocument]`.

P5 ends **before** chunking or embedding.

## Layout

```
experiments/rag_vs_finetuning/
  README.md
  configs/experiment.yaml
  freeze/freeze.py            # deterministic freeze + verify tool
  projection/
    models.py                # RetrievalDocument, SourceReference (engine-neutral)
    project.py               # CanonicalProgram -> list[RetrievalDocument]
    run.py                   # project the corpus + persist JSONL + report
  data/
    frozen_subset/
      programs/<program_id>.json          # 12 immutable canonical records
      sources/<program_id|_index>/<hash>.html   # immutable source snapshots
    manifests/freeze_manifest.json        # checksummed freeze manifest
    projected_documents/documents.jsonl   # deterministic projected documents (P6 input)
    projection_report.json                # machine-readable projection summary
  artifacts/                 # git-ignored: future Chroma store / model weights
```

## Immutability

The frozen corpus is **immutable**. `freeze.verify_frozen_corpus()` recomputes
every record and source checksum from the committed files and compares them to
the manifest. An identical re-run is a deterministic no-op; a changed re-run
without a new `corpus_version` fails. Never edit frozen files in place — any
change requires a new `freeze_id` / `corpus_version`.

## Projection

Deterministic, template-only (no LLM, no timestamps). Sections `overview`,
`admissions`, `application`, `contact` are projected only from **available**
facts. `unknown` / `source_missing` / `manual_required` / `conflicting_sources`
are omitted (conflicting emits a warning); `stale` facts are included with a
caveat. Published deadline text is preserved verbatim — no ISO date is invented.
Document IDs are `"<program_id>::<section>"`.

## Phase P6 — chunking, embeddings, isolated Chroma index

P6 builds `RetrievalDocument → RetrievalChunk → Embedding → isolated Chroma
collection`. It does **not** add retrieval orchestration, prompts, LLM
generation, reranking, or evaluation.

Added packages:

```
chunking/  models.py (RetrievalChunk), chunk.py (policy), run.py (chunks.jsonl + manifest)
embeddings/ embedder.py (SentenceTransformerEmbedder + deterministic FakeEmbedder)
index/     build.py (Chroma build/verify + index_manifest), run.py, cli.py (inspection)
configs/   experiment.yaml (+ chunking/embedding/vector_store), config.py (validated loader)
data/
  chunks/chunks.jsonl                 # deterministic chunks (committed)
  manifests/chunk_manifest.json       # committed
  manifests/index_manifest.json       # committed (Chroma DB itself is NOT committed)
  artifacts/chroma/...                # git-ignored generated Chroma store
```

### Chunking policy

Section-aware, **character-based** (unit = characters, never tokens). Each
projected section fits as one chunk when `len(content) <= chunk_size_characters
(500)`; otherwise it is split into 500-char windows with 75-char overlap. Chunk
IDs are `"<document_id>::chunk::<zero-padded-index>"`. `token_count` is an
approximate whitespace word count (informational; it does not drive chunking).
Identical input + config always yields identical chunks / IDs / offsets /
ordering / `aggregate_chunk_checksum`. A changed config without a new
`chunking_version` fails rather than silently overwriting.

### Embedding

Model `all-MiniLM-L6-v2` (= sentence-transformers/all-MiniLM-L6-v2, dim 384),
`normalize=true`, `device=cpu`, via sentence-transformers directly (no LangChain).
Validation fails on empty content, wrong dimension, and NaN/inf. Reproducibility:
within one locked environment (same model files, library versions, device,
normalization) IDs/ordering/count/dimension/metadata are stable; **bit-for-bit
float equality across different hardware/backends is not claimed**.

### Vector store

Chroma `PersistentClient` under the git-ignored
`artifacts/chroma/masters_track_a_v1`, collection `masters_track_a_v1`, cosine
distance. Record id == `chunk_id`. Flat primitive metadata carries full
provenance (`source_ids`, `source_hashes`, `canonical_record_hash`, versions,
`embedding_model`). The build is idempotent (upsert), verifies exact membership
(no missing/extra), and guards against mixing experiment versions. The
production Chroma collection (`chroma_db/`, `csulb_grad_center`) is never touched.

### Build & inspect

```
# build (chunk -> embed -> index); writes committed manifests, ignored Chroma DB
python -c "from experiments.rag_vs_finetuning.chunking.run import run_chunking; \
          from pathlib import Path; run_chunking(Path('experiments/rag_vs_finetuning/data'))"
python -m experiments.rag_vs_finetuning.index.cli summary
python -m experiments.rag_vs_finetuning.index.cli program accountancy
python -m experiments.rag_vs_finetuning.index.cli chunk accountancy::overview::chunk::000
python -m experiments.rag_vs_finetuning.index.cli verify
```

Reproducible source artifacts (committed): frozen corpus, projection JSONL,
chunks JSONL, manifests, config. The Chroma DB is rebuildable from these; it is
generated and git-ignored.

## P6 → P7 boundary / deferred

Deferred (not implemented in P6): production retrieval integration, the final
query pipeline, prompt construction, LLM answer generation, answer citations,
Track A evaluation, Track B (LoRA/QLoRA) fine-tuning, Track C hybrid, and
comparison metrics. P6 output — the isolated, verified vector index — is the
retrieval substrate consumed by P7 (Track A Pure RAG baseline).

## Phase P7 — Track A: Pure RAG baseline

`track_a/` implements the first complete retrieval pipeline:

```
question → embed query → search Chroma (top-k) → build grounded prompt
        → base LLM (qwen2.5:7b-instruct via Ollama) → grounded answer
        → citations (from retrieved evidence) → full trace
```

Modules: `retriever.py` (query embed + Chroma search + `RetrievalResult`),
`prompt.py` (deterministic `rag_prompt_v1`), `llm.py` (isolated `OllamaLLM` via
`/api/chat` + deterministic `MockLLM` for tests), `pipeline.py` (`ask()` →
`RunTrace`), `trace.py` (JSONL persistence), `cli.py`, `smoke_questions.py`.

- **Retrieval:** same P6 embedding model; configurable `top_k` (4) and
  `similarity_threshold` (0.0, not tuned against any eval set); cosine
  similarity = 1 − distance; deterministic order (similarity desc, chunk_id
  tiebreak); provenance preserved. Read-only against the collection.
- **Prompt (`rag_prompt_v1`):** answer ONLY from retrieved context; never
  fabricate; preserve deadline wording verbatim; treat absent facts as
  unknown/source-missing; cite evidence; say exactly *"I don't have that
  information in the provided sources."* when evidence is insufficient.
- **Generation:** base model `qwen2.5:7b-instruct`, temperature 0, top_p 1,
  seed 0, max_tokens 512 (deterministic-leaning; Ollama greedy decoding is not
  guaranteed bit-identical across versions).
- **Citations:** always derived from the actually-retrieved evidence chunks
  (chunk_id + program + section + source ids/hashes) — never hallucinated. On
  insufficient evidence, no citations are emitted.
- **Failure modes:** no retrieved chunks / all below threshold → refuse without
  calling the model; an insufficient model answer → no citations. Never
  fabricates.
- **Traces:** every run persists a full `RunTrace` (question, retrieved chunk
  ids, scores, prompt version + text, model, generation config, answer,
  citations, latencies, token counts) to a **git-ignored** traces path — the
  committed reproducible artifacts remain the frozen corpus / projection /
  chunks / manifests, not volatile LLM outputs. Traces are the future evaluation
  input.

Commands:

```
python -m experiments.rag_vs_finetuning.track_a.cli retrieve "<question>"
python -m experiments.rag_vs_finetuning.track_a.cli ask "<question>"
python -m experiments.rag_vs_finetuning.track_a.cli trace
python -m experiments.rag_vs_finetuning.track_a.cli verify
```

**Deferred (P8+):** Track B fine-tuning (no retrieval), Track C hybrid,
reranking, hybrid retrieval, agents/tool-calling, production integration, and any
approach comparison. The `smoke_questions.py` set is for debugging only — it is
NOT the evaluation dataset.

## Phase P7.1 — Frozen evaluation benchmark

`evaluation/` defines the **frozen** benchmark reused UNCHANGED by Tracks A, B,
and C. It does not improve retrieval/prompts/generation.

- **Dataset:** `data/evaluation/eval_dataset.json` — **84 cases**, checksummed
  and marked `frozen: true`. Categories: overview 12, application 12, contact 12,
  admissions 5, multi_field 8, retrieval_challenge 10, unknown 12, source_missing
  13. All 12 programs represented (5–9 each). Answerable 59, non-answerable 25.
- **Ground truth:** every expected answer is derived **only** from the frozen
  corpus chunks (never from generated/Track-A output); answerable cases carry
  supporting `expected_citation_targets`; unknown/source_missing cases carry no
  expected answer and no citations (the correct behavior is to abstain / never
  fabricate). Validated: source-missing/unknown facts (STEM, tuition, ranking,
  college, …) are confirmed absent from the corpus.
- **Runner (`runner.py`) + metrics (`metrics.py`):** deterministic, **no LLM
  judge**. Scores answer accuracy, citation precision/recall, hallucination rate,
  abstention accuracy, retrieval recall@k / precision@k, latencies, answer size,
  and failure counts — track-agnostic (consumes `ResponseRecord`s).
- **CLI:** `python -m experiments.rag_vs_finetuning.evaluation.cli {validate|summary}`.

**Frozen:** after P7.1 no evaluation question is added, removed, or modified; the
`dataset_checksum` guards against silent changes. **No benchmark numbers are
produced in this phase** — the machinery is built and unit-tested only; scoring
real tracks (A/B/C) happens later.

## Phase P7.2 — Track A baseline execution

`evaluation/execute.py` runs the **frozen** Track A pipeline (unchanged
retrieval/prompt/model/params) on all 84 frozen cases and persists an immutable
official response per case (`data/evaluation/results/track_a_responses.jsonl`):
question id/category/program, retrieved chunk ids + similarity scores, prompt
version, model, answer, citations, per-stage latencies, answer size, timestamp,
and versions. `evaluation/report.py` then scores those responses with the
existing (unmodified) runner and produces the **official Track A baseline
report** (`data/evaluation/reports/track_a_baseline.{json,md}`): overall metrics,
per-category and per-program breakdowns, retrieval diagnostics (avg retrieved
chunks, avg similarity, most/never-retrieved chunks, no-chunk questions), and an
automatic failure analysis (incorrect answers, hallucinations, missing/incorrect
citations, retrieval failures, abstention errors), grouped by category with
examples.

```
python -m experiments.rag_vs_finetuning.evaluation.cli run-track-a      # execute (real Qwen)
python -m experiments.rag_vs_finetuning.evaluation.cli baseline-report  # score + write report
```

Reproducibility: retrieval, scoring, and report generation are deterministic;
LLM decoding is greedy (temperature 0) but not guaranteed bit-identical across
Ollama versions, so the committed responses/report are a snapshot. **This report
is the official Track A baseline that Tracks B and C will be compared against.**
The system is not tuned based on results.

## Phase P8.0 — Frozen fine-tuning dataset

`training/` builds the **frozen supervised fine-tuning (SFT) dataset** for Track
B, derived **only** from the frozen P5 corpus (projected documents + canonical
records) — never from Track A responses, evaluation outputs, or benchmark
questions. **No model is trained in this phase.**

- **Generation (`generate.py`):** deterministic, template-based. Answerable
  examples take their answer verbatim from the grounded projected section content
  (overview/admissions/application/contact) plus multi-field combinations;
  refusal examples teach the exact refusal *"I don't have enough information in
  the provided Graduate Center data to answer that."* for every `source_missing`/
  `unknown` field (STEM, college, unpublished GPA, GRE). Instruction templates are
  deliberately distinct from the benchmark templates.
- **Validation (`validate.py`):** answerable outputs must exactly equal the
  grounded corpus content (no invented/paraphrased facts); refusals must match the
  canonical text; no empty/duplicate/malformed records; **no instruction may
  overlap an evaluation-benchmark question** (leakage guard).
- **Split (`split.py`):** deterministic 90/10 train/val, seed 42.
- **Export (`export.py`):** Alpaca JSONL (`instruction`/`input`/`output`) +
  per-split files + a conversational export + full audit records, plus a
  checksummed `ft_manifest.json` that freezes the dataset.

Artifacts (committed under `data/training/`): `ft_dataset.jsonl`,
`ft_train.jsonl`, `ft_val.jsonl`, `ft_conversational.jsonl`, `ft_records.jsonl`,
`ft_manifest.json`. Current build: **134 examples** (90 answerable + 44 refusals),
all 12 programs, train 121 / val 13, checksum `sha256:ee143059…`.

```
python -m experiments.rag_vs_finetuning.training.cli build-ft-dataset
python -m experiments.rag_vs_finetuning.training.cli dataset-stats
```

**This frozen dataset is the sole training dataset for Track B.** Deferred (P8.1+):
LoRA/QLoRA fine-tuning, adapter generation, Track B inference, and any comparison.
