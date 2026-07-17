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
