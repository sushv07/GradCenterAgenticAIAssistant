"""
experiments/rag_vs_finetuning/index/run.py
Orchestrate the isolated experiment index build (Phase P6).

Loads the deterministic chunk artifacts, verifies the chunk checksum, embeds via
the injected embedder, builds the isolated Chroma collection, verifies exact
membership, and writes index_manifest.json (the Chroma DB stays under the
git-ignored artifacts path).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from experiments.rag_vs_finetuning.chunking.chunk import aggregate_chunk_checksum
from experiments.rag_vs_finetuning.chunking.models import RetrievalChunk
from experiments.rag_vs_finetuning.configs.config import ExperimentConfig, load_config
from experiments.rag_vs_finetuning.index.build import (
    IndexError_, build_collection, build_index_manifest,
)


def load_chunks(chunks_jsonl: Path) -> list[RetrievalChunk]:
    lines = Path(chunks_jsonl).read_text(encoding="utf-8").strip().splitlines()
    return [RetrievalChunk.model_validate_json(l) for l in lines if l.strip()]


def _repo_root(data_root: Path) -> Path:
    # data_root = <repo>/experiments/rag_vs_finetuning/data
    return Path(data_root).resolve().parents[2]


def run_index_build(*, embedder, config: Optional[ExperimentConfig] = None,
                    git_commit: str, now: Optional[datetime] = None,
                    clean: bool = False, persist_dir: Optional[Path] = None) -> dict:
    config = config or load_config()
    now = now or datetime.now(timezone.utc)
    data_root = Path(config.corpus.data_root)
    if not data_root.is_absolute():
        # resolve relative to CWD (repo root in normal use)
        data_root = Path.cwd() / data_root

    chunk_manifest = json.loads((data_root / "manifests" / "chunk_manifest.json").read_text("utf-8"))
    freeze_manifest = json.loads((data_root / "manifests" / "freeze_manifest.json").read_text("utf-8"))
    projection_report = json.loads((data_root / "projection_report.json").read_text("utf-8"))

    chunks = load_chunks(data_root / "chunks" / "chunks.jsonl")
    if aggregate_chunk_checksum(chunks) != chunk_manifest["aggregate_chunk_checksum"]:
        raise IndexError_("chunks.jsonl checksum does not match chunk_manifest")

    if persist_dir is None:
        persist_dir = _repo_root(data_root) / config.vector_store.persistence_path
    versions = {
        "corpus_version": config.corpus.corpus_version,
        "projection_version": config.projection.version,
        "chunking_version": config.chunking.version,
        "embedding_model": config.embedding.model,
        "index_version": config.vector_store.index_version,
    }
    collection = build_collection(
        chunks, embedder, persist_dir=persist_dir,
        collection_name=config.vector_store.collection_name,
        distance=config.vector_store.distance_metric, versions=versions, clean=clean)

    manifest = build_index_manifest(
        collection=collection, chunks=chunks, embedder=embedder,
        collection_name=config.vector_store.collection_name, persist_dir=persist_dir,
        distance=config.vector_store.distance_metric,
        corpus_version=config.corpus.corpus_version, freeze_id=freeze_manifest["freeze_id"],
        projection_version=projection_report["projection_version"],
        projection_checksum=projection_report["aggregate_projection_checksum"],
        chunking_version=config.chunking.version,
        chunk_checksum=chunk_manifest["aggregate_chunk_checksum"],
        index_version=config.vector_store.index_version, git_commit=git_commit, now=now)

    out = data_root / "manifests" / "index_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return manifest
