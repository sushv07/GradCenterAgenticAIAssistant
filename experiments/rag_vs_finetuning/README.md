# RAG vs. Fine-Tuning Experiment

A self-contained, frozen engineering study comparing three architectures for a
factual assistant over the CSULB Graduate Center master's programs:

- **Track A — Pure RAG** (retrieval-grounded generation)
- **Track B — LoRA Fine-Tuning** (parametric adaptation, no retrieval)
- **Track C — Hybrid** (Track A retrieval feeding the Track B adapter)

Isolated by design: it reads frozen canonical program records **read-only** and
imports **no** production RAG, routing, orchestration, LangChain, Chroma,
embeddings, or model-serving code; production code never imports this package.

**Key Takeaway**

This controlled study compared three architectures—Pure RAG, LoRA Fine-Tuning, and a Hybrid approach—using the same frozen corpus, benchmark, and evaluation pipeline. Within the scope of this study, Pure RAG consistently produced the highest factual accuracy, safest failure behavior, and strongest production characteristics, while the hybrid implementation demonstrated that retrieval quality alone is insufficient without a retrieval-aware generator.

> **Start here for results, not code:** the executed study spans phases P5–P12.
> This README is the navigation guide and build log. The narrative conclusions,
> per-track metrics, and comparisons live in dedicated reports — linked below
> under [Official results](#official-results) and [Document index](#document-index).

## Objective

Determine, under controlled conditions, whether **retrieval (RAG)**, **small-data
LoRA fine-tuning**, or their **hybrid** best answers grounded factual questions
about the programs, when institutional knowledge is factual/updatable and the
supervised dataset is small. Every track is held to one frozen corpus, one frozen
84-case benchmark, and one shared evaluation pipeline so each track changes exactly
one variable.

## Research questions

1. Does Pure RAG perform well on grounded factual QA?
2. Can small-data LoRA fine-tuning replace retrieval as the knowledge source?
3. Does a Hybrid (RAG + fine-tuned adapter) improve over Pure RAG?
4. What role does retrieval grounding play relative to model weights?
5. When is fine-tuning the appropriate tool?

Answers, with evidence, are in [`reports/final_conclusions.md`](reports/final_conclusions.md)
(§4) and the three-way comparison
[`data/evaluation/reports/comparative_analysis_abc.md`](data/evaluation/reports/comparative_analysis_abc.md).

## Repository organization

Pipeline order (each stage's committed output feeds the next; the Chroma DB and
model weights are git-ignored and rebuildable):

```
freeze/ ─▶ projection/ ─▶ chunking/ ─▶ embeddings/ ─▶ index/   (P5–P6: corpus → vector index)
                                                     │
                       ┌─────────────────────────────┼───────────────────────────┐
                       ▼                             ▼                            ▼
                  track_a/  (Pure RAG)          training/ + track_b/          track_c/
                       │                         (SFT data + LoRA + FT eval)   (Hybrid)
                       └───────────────▶ evaluation/ (frozen benchmark + scoring) ◀┘
                                                     │
                                                 analysis/  (A-vs-B, A-vs-B-vs-C)
```

| Package | Role |
| --- | --- |
| `freeze/`, `projection/` | Immutable 12-program corpus + `CanonicalProgram → RetrievalDocument` (P5) |
| `chunking/`, `embeddings/`, `index/` | Deterministic chunks (41) → `all-MiniLM-L6-v2` → isolated Chroma `masters_track_a_v1` (P6) |
| `track_a/` | Pure RAG pipeline: retrieve → grounded prompt → base LLM → cited answer (P7) |
| `training/` | Frozen SFT dataset builder + MLX LoRA config (`training/mlx/`) (P8.0/P8.1) |
| `track_b/` | Fine-tuned inference (no retrieval) + evaluator (P8.2) |
| `track_c/` | Hybrid: frozen retrieval + Track B adapter — see [`track_c/README.md`](track_c/README.md) (P10/P11) |
| `evaluation/` | Frozen 84-case benchmark, deterministic scoring (no LLM judge), shared by A/B/C (P7.1) |
| `analysis/` | Two-way (`compare.py`) and three-way (`compare_abc.py`) comparisons (P9/P11) |
| `configs/` | `experiment.yaml` + validated loader (`config.py`) |
| `data/` | Committed artifacts (corpus, chunks, manifests, dataset, benchmark, responses, reports) |
| `reports/` | Final synthesis (conclusions, exec summary, lessons, future work) — P12 |
| `artifacts/` | Git-ignored generated Chroma store, adapters, logs |

Unit tests live in the repo root: `tests/test_experiment_*.py` (freeze, projection,
chunking, embeddings, index, track_a, evaluation, training, isolation).

## Tracks at a glance

| Track | Knowledge source | Generator | Retrieval | Detailed doc |
| --- | --- | --- | --- | --- |
| **A** Pure RAG | Chroma retrieval | `qwen2.5:7b-instruct` (Ollama) | top_k=4, thr=0.0 | build log below (P7) |
| **B** Fine-Tuned | adapter weights | `Qwen2.5-7B-Instruct-4bit` + LoRA (MLX) | disabled | [`track_b_training_report.md`](data/training/track_b_training_report.md) |
| **C** Hybrid | Chroma retrieval (authoritative) | base 4-bit + LoRA (MLX) | top_k=4, thr=0.0 | [`track_c/README.md`](track_c/README.md) |

## Dataset

The frozen supervised fine-tuning dataset (Track B/C training only) is built from
the frozen corpus — never from Track A output, evaluation, or benchmark questions
(leakage-guarded). **134 examples** (90 answerable + 44 refusals), train 121 / val
13 (seed 42), checksum `sha256:ee143059…`. Committed under `data/training/`
(`ft_dataset.jsonl`, `ft_train.jsonl`, `ft_val.jsonl`, `ft_records.jsonl`,
`ft_manifest.json`; MLX chat-format derivative in `data/training/mlx/`). Full
construction rules: [build log §Phase P8.0](#phase-p80--frozen-fine-tuning-dataset).

## Benchmark

The evaluation benchmark is separate and frozen: `data/evaluation/eval_dataset.json`
— **84 cases**, `frozen: true`, checksum-guarded. 8 categories (overview 12,
application 12, contact 12, admissions 5, multi_field 8, retrieval_challenge 10,
unknown 12, source_missing 13); 59 answerable, 25 non-answerable. Ground truth is
derived only from frozen corpus chunks; should-abstain cases (`unknown`,
`source_missing`) carry no expected answer. Details:
[build log §Phase P7.1](#phase-p71--frozen-evaluation-benchmark).

## Evaluation methodology

One deterministic, track-agnostic pipeline (`evaluation/runner.py` +
`evaluation/metrics.py`), **no LLM judge**, consuming a shared `ResponseRecord`
schema so A/B/C are scored identically. Each track is executed on the 84 frozen
cases, persisted to `data/evaluation/results/track_{a,b,c}_responses.jsonl`, then
scored into `data/evaluation/reports/track_{a,b,c}_evaluation` (Track A:
`track_a_baseline`). Every track's recompute reproduces its committed report
exactly. Scoring uses deterministic substring/set matching — a documented proxy,
not an LLM judge.

## Reproducibility

- **Configs:** `configs/experiment.yaml` (chunking, embedding, vector store,
  `track_a` retrieval params); MLX training config frozen at
  `training/mlx/train_config.yaml`.
- **Seeds:** dataset split seed 42; training seed 42; decoding greedy (temperature 0).
- **Checkpoint selection:** the official Track B adapter is the **lowest-validation-loss**
  checkpoint (iter 40, val 1.018), not the final step — see
  [`data/training/track_b_reproducibility.json`](data/training/track_b_reproducibility.json)
  for the exact MLX command, versions, and hardware.
- **Checksums:** corpus/chunks/index/benchmark/dataset/adapter are SHA-256 guarded;
  `freeze.verify_frozen_corpus()` re-verifies the corpus; the selected adapter is
  `sha256:a2a09086…`; benchmark `sha256:e6f4145c…`; SFT dataset `sha256:ee143059…`.
- **Interpreter split (important):** retrieval needs `chromadb`/`sentence-transformers`
  (miniconda Python 3.13); MLX generation needs `mlx_lm` (CommandLineTools/Xcode
  Python 3.9). No single interpreter has both — Track C bridges them via a JSON
  hand-off (see [`track_c/README.md`](track_c/README.md)).
- **Rebuild order:** run stages in pipeline order above; committed source artifacts
  are sufficient to regenerate the git-ignored Chroma DB and re-run evaluation.

## Metrics

Answer accuracy, completeness, hallucination rate, abstention accuracy, refusal
rate, unsupported-claim rate, citation precision/recall, retrieval recall@k /
precision@k, latency, and failure-mode counts. Definitions are implemented in
`evaluation/metrics.py` (+ derived metrics in `track_b/evaluate.py`).

## Official results

Headline metrics on the frozen 84-case benchmark (identical pipeline for all
tracks). **All figures are from the committed reports; none are estimated.**

| Metric | Track A (RAG) | Track B (FT) | Track C (Hybrid) |
| --- | --- | --- | --- |
| Answer accuracy | **0.4576** | 0.0678 | 0.0169 |
| Hallucination rate | **0.16** | 1.00 | 1.00 |
| Abstention accuracy | **0.84** | 0.00 | 0.00 |
| Refusal rate | 0.5714 | 0.1071 | 0.0000 |
| Unsupported-claim rate | **0.25** | 0.9467 | 0.9881 |
| Citation recall | 0.5254 | 0.00 | 0.5593 |
| Retrieval recall@k | 0.5593 | n/a | 0.5593 |

Track A achieved the strongest performance across all eight evaluation categories. Notably, Tracks A and C received **identical
retrieval** (retrieval recall@k 0.5593 for both) yet scored 0.4576 vs 0.0169 —
isolating the context-free, overfit adapter as the binding constraint.

Per-track and comparative detail:
[`track_a_baseline.md`](data/evaluation/reports/track_a_baseline.md) ·
[`track_b_evaluation.md`](data/evaluation/reports/track_b_evaluation.md) ·
[`track_c_evaluation.md`](data/evaluation/reports/track_c_evaluation.md) ·
[`comparative_analysis.md`](data/evaluation/reports/comparative_analysis.md) (A vs B) ·
[`comparative_analysis_abc.md`](data/evaluation/reports/comparative_analysis_abc.md) (A vs B vs C).

## Engineering conclusions

Within the scope of this study, retrieval grounding is the dominant factor for
factual, updatable QA; small-data LoRA neither replaced retrieval nor improved a
RAG pipeline, and a context-free overfit adapter degraded generation even when
supplied correct evidence. Full write-ups:
[`reports/final_conclusions.md`](reports/final_conclusions.md),
[`reports/executive_summary.md`](reports/executive_summary.md),
[`reports/lessons_learned.md`](reports/lessons_learned.md).

## Future work

Retrieval-aware fine-tuning, larger/cleaner SFT data, rerankers/query expansion,
cross-family validation, larger benchmarks, and LLM-judge evaluation:
[`reports/future_work.md`](reports/future_work.md).

## Document index

- **Synthesis (P12):** [`reports/final_conclusions.md`](reports/final_conclusions.md) ·
  [`reports/executive_summary.md`](reports/executive_summary.md) ·
  [`reports/lessons_learned.md`](reports/lessons_learned.md) ·
  [`reports/future_work.md`](reports/future_work.md) ·
  [`reports/final_conclusions.json`](reports/final_conclusions.json)
- **Per-track evaluation:** [`track_a_baseline.md`](data/evaluation/reports/track_a_baseline.md) ·
  [`track_b_evaluation.md`](data/evaluation/reports/track_b_evaluation.md) ·
  [`track_c_evaluation.md`](data/evaluation/reports/track_c_evaluation.md)
- **Comparisons:** [`comparative_analysis.md`](data/evaluation/reports/comparative_analysis.md) ·
  [`comparative_analysis_abc.md`](data/evaluation/reports/comparative_analysis_abc.md)
- **Training:** [`track_b_training_report.md`](data/training/track_b_training_report.md) ·
  [`track_b_reproducibility.json`](data/training/track_b_reproducibility.json)
- **Track C design/validation:** [`track_c/README.md`](track_c/README.md) ·
  [`track_c/FUNCTIONAL_VALIDATION.md`](track_c/FUNCTIONAL_VALIDATION.md)
- **Repo-wide architecture context:** [`../../ARCHITECTURE_ANALYSIS.md`](../../ARCHITECTURE_ANALYSIS.md)
  (see "Experiment Retrospective — RAG vs Fine-Tuning vs Hybrid").

---

# Build log (phase-by-phase, P5–P12)

*The sections below are the chronological engineering log. P5–P8.0 document the
frozen corpus → vector index → Track A baseline → SFT dataset build; P8.1–P12
summarize training, per-track evaluation, comparison, and synthesis, cross-linking
the reports above rather than repeating their numbers.*

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

## Phase P8.0.5 — MLX training environment validation

Validated the Apple Silicon (M4, 16 GB) MLX / MLX-LM LoRA stack before any official
training — model loads, adapter trains/saves, inference runs in-budget — with no
official training, benchmark, or dataset changes. Surfaced the **interpreter split**
(3.13 retrieval vs 3.9 MLX) that shapes Tracks B and C.

## Phase P8.1 — Official LoRA fine-tuning (Track B training)

Single official training run: a LoRA adapter over frozen
`mlx-community/Qwen2.5-7B-Instruct-4bit` on the frozen 121/13 split via MLX-LM.
Config frozen at [`training/mlx/train_config.yaml`](training/mlx/train_config.yaml)
(rank 16, scale 20, dropout 0.05, 16 layers, LR 1e-4, 200 iters, seed 42; 23.069M
trainable params, 0.303%). Validation loss minimized at **iter 40** then diverged
(overfitting); the **iter-40 checkpoint** was selected as the official adapter
(`artifacts/adapters/track_b_selected/`, `sha256:a2a09086…`). Full report + manifest:
[`data/training/track_b_training_report.md`](data/training/track_b_training_report.md),
[`track_b_reproducibility.json`](data/training/track_b_reproducibility.json).

## Phase P8.2 — Track B official evaluation

Ran base + selected adapter over the 84-case benchmark through the shared pipeline
with **retrieval disabled** (empty retrieved/citation ids). Code: `track_b/infer.py`
(generation), `track_b/evaluate.py` (scoring). Official metrics and error analysis:
[`data/evaluation/reports/track_b_evaluation.md`](data/evaluation/reports/track_b_evaluation.md).

## Phase P9 — Comparative analysis (Track A vs Track B)

`analysis/compare.py` re-scored both tracks through the unmodified pipeline (each
reproduced its frozen report) and produced
[`comparative_analysis.md`](data/evaluation/reports/comparative_analysis.md),
whose forward recommendation seeded Track C.

## Phase P10 — Track C: Hybrid (RAG + LoRA) implementation

Frozen Track A retrieval feeding a grounded prompt consumed by base + Track B
adapter; retrieval is authoritative, the adapter shapes behaviour only. Modules:
`track_c/retrieve.py` (3.13), `track_c/prompt_builder.py`, `track_c/infer.py` (3.9),
`track_c/cli.py`. Engineering-only (no benchmark/metrics); functional validation
passed. Design + validation:
[`track_c/README.md`](track_c/README.md),
[`track_c/FUNCTIONAL_VALIDATION.md`](track_c/FUNCTIONAL_VALIDATION.md).

## Phase P11 — Track C official evaluation

Precomputed retrieval bundle
(`data/evaluation/results/track_c_retrieval_bundle.jsonl`) + `track_c/evaluate.py`
scoring. Track C received **identical retrieval to Track A** yet scored far lower —
isolating the adapter as the constraint. Report:
[`track_c_evaluation.md`](data/evaluation/reports/track_c_evaluation.md); three-way
comparison: [`comparative_analysis_abc.md`](data/evaluation/reports/comparative_analysis_abc.md).

## Phase P12 — Final conclusions

Documentation-only synthesis under [`reports/`](reports/): conclusions, executive
summary, lessons learned, future work (see [Document index](#document-index)). No
training/inference/evaluation; all frozen artifacts unchanged.
