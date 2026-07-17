"""
experiments/rag_vs_finetuning/track_a/retriever.py
Deterministic query -> embedding -> Chroma search -> top-k chunks (Phase P7).

Uses the SAME embedding model as P6 (injected embedder). Read-only against the
verified experiment collection; never modifies it. Ordering is deterministic
(by descending similarity, then chunk_id for ties). Provenance is preserved.
"""
from __future__ import annotations

import time

from experiments.rag_vs_finetuning.projection.models import SourceReference
from experiments.rag_vs_finetuning.track_a.models import (
    RetrievalResult, RetrievedChunkRef,
)

RETRIEVAL_VERSION = "retrieval-0.1"


def _similarity(distance: float) -> float:
    # cosine distance on normalized vectors: similarity = 1 - distance
    return round(1.0 - float(distance), 6)


def _source_refs(md: dict) -> list[SourceReference]:
    ids = [s for s in (md.get("source_ids", "") or "").split(",") if s]
    hashes = [h for h in (md.get("source_hashes", "") or "").split(",") if h]
    urls = [""] * len(ids)  # snapshot URL is not stored in flat chroma metadata
    return [SourceReference(source_id=i, source_url=u, content_hash=h)
            for i, u, h in zip(ids, urls, hashes)]


def retrieve(question: str, *, embedder, collection, top_k: int = 4,
             threshold: float = 0.0, distance_metric: str = "cosine") -> RetrievalResult:
    start = time.perf_counter()
    query_vec = embedder.embed([question])
    res = collection.query(query_embeddings=query_vec, n_results=top_k,
                           include=["metadatas", "documents", "distances"])
    metas = res["metadatas"][0]
    docs = res["documents"][0]
    dists = res["distances"][0]
    ids = res["ids"][0]

    rows = []
    for cid, md, doc, dist in zip(ids, metas, docs, dists):
        sim = _similarity(dist)
        if sim < threshold:
            continue
        rows.append(RetrievedChunkRef(
            chunk_id=cid, document_id=md.get("document_id", ""),
            program_id=md.get("program_id", ""), section=md.get("section", ""),
            similarity_score=sim, source_references=_source_refs(md), content=doc))
    # deterministic ordering: highest similarity first, chunk_id tiebreak
    rows.sort(key=lambda r: (-r.similarity_score, r.chunk_id))
    latency = round((time.perf_counter() - start) * 1000, 3)
    return RetrievalResult(
        query=question, query_embedding_model=embedder.info.model_id,
        retrieved_chunks=rows, similarity_scores=[r.similarity_score for r in rows],
        retrieval_latency_ms=latency, top_k=top_k, threshold=threshold,
        distance_metric=distance_metric, retrieval_version=RETRIEVAL_VERSION)
