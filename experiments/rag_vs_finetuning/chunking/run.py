"""
experiments/rag_vs_finetuning/chunking/run.py
Chunk the frozen projection into deterministic artifacts (Phase P6).

Reads the P5 documents.jsonl + projection checksum, chunks section-aware, and
writes chunks.jsonl + chunk_manifest.json. An identical rerun is a deterministic
no-op; a changed chunking configuration must bump the chunking version (a version
mismatch against an existing manifest raises).
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.chunking.chunk import (
    ChunkConfig, aggregate_chunk_checksum, build_chunk_manifest, chunk_documents,
    load_projected_documents, persist_chunks,
)


def run_chunking(data_root: Path, config: ChunkConfig = ChunkConfig()) -> dict:
    data_root = Path(data_root)
    documents_jsonl = data_root / "projected_documents" / "documents.jsonl"
    projection_report = json.loads((data_root / "projection_report.json").read_text("utf-8"))
    projection_version = projection_report["projection_version"]
    projection_checksum = projection_report["aggregate_projection_checksum"]

    documents = load_projected_documents(documents_jsonl)
    chunks = chunk_documents(documents, config)
    manifest = build_chunk_manifest(
        chunks, config=config, projection_version=projection_version,
        projection_checksum=projection_checksum, document_count=len(documents),
        generated_from="experiments/rag_vs_finetuning/data/projected_documents/documents.jsonl")

    manifest_path = data_root / "manifests" / "chunk_manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text("utf-8"))
        if existing.get("chunking_version") == config.version:
            if existing.get("aggregate_chunk_checksum") == manifest["aggregate_chunk_checksum"]:
                return existing  # deterministic no-op
            raise ValueError("chunk content changed but chunking_version unchanged; bump version")

    persist_chunks(chunks, data_root / "chunks" / "chunks.jsonl")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return manifest
