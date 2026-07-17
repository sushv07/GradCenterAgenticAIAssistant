"""
experiments/rag_vs_finetuning/index/build.py
Isolated Chroma index builder + verifier (Phase P6).

Builds an experiment-only Chroma collection under an ignored artifacts path from
the deterministic chunk artifacts. It never touches the production Chroma
collection, embeds via the injected experiment embedder, upserts idempotently
(stable chunk_id == Chroma record id), verifies exact membership, and writes a
committed index_manifest.json (the generated Chroma DB itself is git-ignored).

No LLM, no retrieval orchestration, no reranking, no answer generation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from experiments.rag_vs_finetuning.chunking.models import RetrievalChunk
from experiments.rag_vs_finetuning.embeddings.embedder import embed_chunks

METADATA_SCHEMA_VERSION = "chunk-metadata-1"


class IndexError_(Exception):
    pass


def _chunk_metadata(chunk: RetrievalChunk, embedding_model: str) -> dict:
    m = chunk.metadata
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "program_id": chunk.program_id,
        "canonical_name": m.get("canonical_name", ""),
        "degree_type": m.get("degree_type", ""),
        "program_level": chunk.program_level,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        "source_ids": ",".join(s.source_id for s in chunk.source_references),
        "source_hashes": ",".join(s.content_hash for s in chunk.source_references),
        "canonical_record_hash": chunk.canonical_record_hash,
        "projection_version": chunk.projection_version,
        "chunking_version": chunk.chunking_version,
        "embedding_model": embedding_model,
        "freshness_status": chunk.freshness_status,
        "volatility": chunk.volatility,
    }


def _collection_metadata(distance: str, versions: dict) -> dict:
    md = {"hnsw:space": distance}
    md.update({f"exp_{k}": v for k, v in versions.items()})
    return md


def build_collection(chunks: list[RetrievalChunk], embedder, *, persist_dir: Path,
                     collection_name: str, distance: str = "cosine",
                     versions: Optional[dict] = None, clean: bool = False):
    import chromadb  # lazy — experiment isolated
    persist_dir = Path(persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))

    if clean:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=collection_name, metadata=_collection_metadata(distance, versions or {}))

    # version-mismatch guard: refuse to mix experiment versions in one collection
    existing_ver = collection.metadata.get("exp_chunking_version") if collection.metadata else None
    want_ver = (versions or {}).get("chunking_version")
    if existing_ver and want_ver and existing_ver != want_ver and not clean:
        raise IndexError_(
            f"collection has chunking_version {existing_ver}, want {want_ver}; "
            "use clean=True to rebuild")

    ordered = sorted(chunks, key=lambda c: c.chunk_id)
    vectors = embed_chunks(embedder, ordered)
    collection.upsert(
        ids=[c.chunk_id for c in ordered],
        embeddings=vectors,
        documents=[c.content for c in ordered],
        metadatas=[_chunk_metadata(c, embedder.info.model_id) for c in ordered],
    )
    return collection


def verify_collection(collection, chunks: list[RetrievalChunk]) -> dict:
    expected = {c.chunk_id for c in chunks}
    got = collection.get(include=[])
    got_ids = set(got["ids"])
    if collection.count() != len(chunks):
        raise IndexError_(f"vector count {collection.count()} != chunk count {len(chunks)}")
    missing = expected - got_ids
    extra = got_ids - expected
    if missing:
        raise IndexError_(f"missing chunk ids in collection: {sorted(missing)[:5]}")
    if extra:
        raise IndexError_(f"extra/stale ids in collection: {sorted(extra)[:5]}")
    # metadata spot-check: every stored id maps to a known chunk
    stored = collection.get(ids=list(expected), include=["metadatas"])
    by_id = {c.chunk_id: c for c in chunks}
    for cid, md in zip(stored["ids"], stored["metadatas"]):
        if md.get("program_id") != by_id[cid].program_id:
            raise IndexError_(f"metadata mismatch for {cid}")
    return {"vector_count": collection.count(), "missing": 0, "extra": 0}


def _identity_hash(fields: dict) -> str:
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_index_manifest(*, collection, chunks, embedder, collection_name, persist_dir,
                         distance, corpus_version, freeze_id, projection_version,
                         projection_checksum, chunking_version, chunk_checksum,
                         index_version, git_commit, now: datetime) -> dict:
    import chromadb
    identity = _identity_hash({
        "corpus_version": corpus_version, "projection_checksum": projection_checksum,
        "chunk_checksum": chunk_checksum, "embedding_model": embedder.info.model_id,
        "dimension": embedder.info.dimension, "normalize": embedder.info.normalize,
        "distance": distance,
    })
    verification = verify_collection(collection, chunks)
    return {
        "index_version": index_version,
        "collection_name": collection_name,
        "corpus_version": corpus_version,
        "freeze_id": freeze_id,
        "projection_version": projection_version,
        "projection_checksum": projection_checksum,
        "chunking_version": chunking_version,
        "chunk_checksum": chunk_checksum,
        "embedding_model": embedder.info.model_id,
        "embedding_dimension": embedder.info.dimension,
        "normalization": embedder.info.normalize,
        "embedding_library": embedder.info.library,
        "embedding_library_version": embedder.info.library_version,
        "device_policy": embedder.info.device,
        "vector_count": collection.count(),
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "build_status": "ok",
        "build_timestamp": now.isoformat(),          # NOT part of identity checks
        "git_commit": git_commit,
        "chroma_version": chromadb.__version__,
        "chroma_persistence_path": str(persist_dir),
        "distance_metric": distance,
        "collection_identity_hash": identity,
        "verification": verification,
    }
