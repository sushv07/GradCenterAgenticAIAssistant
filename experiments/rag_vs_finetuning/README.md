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

## Deferred to later phases

Chunking, embeddings, the experiment Chroma store, retrieval, LLM generation,
Track A (base + RAG), Track B (LoRA/QLoRA), Track C (fine-tuned + RAG), the
freshness experiment, and evaluation metrics. None are implemented in P5.
